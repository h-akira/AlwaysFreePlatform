# 02 構成と決定

[01](01_purpose.md) の目的と方針に沿って決めた構成を書く。

## 1. 前提にした無料枠

無料枠の値と出典は [references/oci-free-tier.md](references/oci-free-tier.md) にある。構成を決めるのに効いたのは次の点。

- **VM**: 無料で確実に作れるのは E2.1.Micro（1/8 OCPU・1 GB）の 2 台。A1（合計 2 OCPU・12 GB）は大きいが、リージョンによっては空きが無く作れないことが多い。
- **DB**: MySQL HeatWave（1 ECPU・8 GB。ECPU は OCI の CPU の数え方の単位）が 1 個。小さなアプリを複数デプロイするには十分。自動バックアップの保持は 1 日で、変えられない。
- **Logging**: ログの保存は月 10 GB まで 0 円。小さなアプリが数個なら収まる見込み（量は測っていない）。
- **ホームリージョン**: Compute と DB は、ホームリージョンにしか無料で作れない。
- **アイドル回収**: Always Free の Compute は、7 日間使用率が低いと回収されうる。個人用のアプリはこれに当たりやすい。
- **無料でないもの**:
  - **OCI DevOps のビルド**。実行の分だけ課金される（額は未確認）。有料のリソースを使うので、PAYG（従量課金）のアカウントが要る見込み（未確認）。
  - **OCIR の保存**。保存量に応じた料金になりうる。古いものを消して小さく保つ。

## 2. 全体の図

```mermaid
flowchart TB
  subgraph local["ローカル"]
    dev["開発: 本番と同じイメージ・同じバージョンの MySQL"]
    deploy["make deploy<br/>（バージョン名は時刻か TAG=）"]
    push["プロジェクトの release に push<br/>（バージョンのタグ付き。自動のデプロイを使うとき）"]
  end
  deploy -->|"イメージ"| reg
  deploy -->|"エージェントに afp deploy を実行させる"| afp
  push --> gh["GitHub"] --> devops["OCI DevOps<br/>リリースのファイルを置く"]
  devops -->|"エージェントに afp deploy を実行させる"| afp
  afp -->|"ビルドして push"| reg[("OCIR<br/>イメージ")]
  user["ブラウザ"] -->|"HTTPS<br/>app-a.example.com<br/>app-b.example.com"| nlb
  subgraph vcn["VCN"]
    subgraph pub["パブリック・サブネット"]
      nlb["NLB<br/>TCP 80・443 を素通し"]
    end
    subgraph vmnet["VM 用サブネット（プライベート）"]
      subgraph vm["VM（ステートレス）"]
        afp["afp"]
        caddy["Caddy<br/>証明書・振り分け"]
        a["プロジェクト A"]
        b["プロジェクト B"]
        caddy --> a & b
      end
    end
    subgraph dbnet["DB 用サブネット（プライベート）"]
      mysql[("MySQL HeatWave<br/>プロジェクトごとに DB とユーザ")]
    end
    subgraph bnet["Bastion 用サブネット（プライベート）"]
      bep["Bastion の接続口"]
    end
    nat["NAT ゲートウェイ<br/>外へ出るだけ"]
    sgw["サービス・ゲートウェイ<br/>OCI のサービスへ"]
  end
  nlb --> caddy
  a & b --> mysql
  vm --> nat & sgw
  reg -. pull .-> vm
  bastion["OCI Bastion"] -. "保守のときだけ" .-> bep
  bep -. "ssh" .-> vm
  bep -. "MySQL" .-> mysql
  vault["OCI Vault"] -. "シークレット" .-> afp
  os[("Object Storage<br/>一覧・今のバージョン・ダンプ・操作のログ")] -. "読み書き" .-> afp
  afp -. "afp check-db（1 時間ごと）" .-> mysql
  afp -. "ダンプの成否・DB とディスクの確かめの結果" .-> mon["OCI Monitoring<br/>アラーム → メール"]
  a & b -. "標準出力（エージェントが送る）" .-> logging[("OCI Logging<br/>アプリのログ")]
```

## 3. コンポーネントと役目

| コンポーネント | 役目 |
|---|---|
| **VM**（OCI Compute） | プロジェクトのコンテナと Caddy を Docker で動かす。`release` ブランチへの push からのデプロイでは、イメージもここでビルドする |
| **Caddy** | 入口。HTTPS を受け、ドメイン名でプロジェクトに振り分ける。証明書（Let's Encrypt）を自動で取得・更新する |
| **NLB**（OCI の Network Load Balancer） | 外からの入口。公開 IP を持ち、TCP の 80 番と 443 番を、そのまま（TLS を解かずに）VM の Caddy へ通す。利用者の IP を書き換えない（§5.4） |
| **OCI DNS** | 基盤の公開 DNS のゾーン。プロジェクトごとの名前（`<プロジェクト>.<ゾーン>`）を、その VM の前の NLB の公開 IP に向ける（§5.4） |
| **`afp`** | 基盤のコマンド（Python の標準ライブラリだけで書く。§5.8）。VM の上で、初期設定・プロジェクトの一覧に合わせた同期（プロジェクトの DB とユーザの作成を含む）・デプロイ・DB のダンプ・基盤の監視のうちの定期的な確かめ（DB が答えるか、ディスクの使用率。§5.7）を受け持つ。外からは、VM の中のエージェント（Oracle Cloud Agent の Run Command）を通して呼ぶ（§5.6） |
| **MySQL HeatWave** | 全プロジェクトで共有する DB。プロジェクトごとにデータベースとユーザを分ける |
| **OCI Vault** | シークレットの保存先。生成できる値は Terraform が生成して Vault に置く（値は Resource Manager の state にも残る）。外から持ってくる秘密の値（GitHub のトークン・外部の API キー）は、管理者が手で作る（§5.5） |
| **Object Storage** | 役目ごとに 3 つのバケット（§5.10）。プロジェクトの一覧・各プロジェクトの今のバージョン・リリースのファイル・基盤のコード、DB のダンプ、`afp` の操作のログ |
| **OCIR**（OCI のコンテナ・レジストリ。[references/oci-registry.md](references/oci-registry.md)） | ビルドしたイメージ。リポジトリはプロジェクトのサービスごと |
| **OCI DevOps** | リポジトリを伝えたプロジェクトの `release` ブランチへの push を受けて、そのプロジェクトのリリースのファイルを Object Storage に置き、VM に `afp deploy` を実行させる（§5.6） |
| **OCI Monitoring・Notifications** | 基盤の監視（§5.7）。週 1 回のダンプ（§5.3）の成否、NLB のヘルスチェックの結果、DB が答えるか、VM のメモリとディスクを受け、アラームがメールで通知する |
| **OCI Logging** | アプリのログ（コンテナの標準出力・標準エラー）を、全プロジェクトまとめて 1 つのログに残す（§5.11）。VM の中の Oracle Cloud Agent が送る |
| **VCN** | 基盤のネットワーク。サブネットを役目ごとに 4 つに分ける（§5.4） |
| **OCI Bastion** | ローカルからプライベート・サブネットの VM と DB に入るための、一時的な接続口（§5.9） |
| **Terraform**（OCI Resource Manager で実行。[references/oci-resource-manager.md](references/oci-resource-manager.md)） | VM の外のものを作る。プロジェクトの一覧から、プロジェクトごとの生成するシークレットとパイプラインも作る。ローカルの `terraform/` を、そのまま（git に頼らず）送って実行する |

- **VM の外は Terraform、VM の中は `afp`** が受け持つ。`afp` は Terraform が書いたプロジェクトの一覧に従う。
- プロジェクトの DB とユーザは、Terraform でなく VM の `afp` が、Vault に置いた DB の管理者のパスワードで作る。
- **基盤の監視**（§5.7）は、基盤が動いているかを見ること。コンテナが正しく動いているかを確かめる compose の `healthcheck` とは別のもの。
- デプロイに要るファイル（リリースのファイル。プロジェクトのそのバージョンの `compose.afp.yaml`）は、バケットにバージョンごとに置く。VM は使うたびにバケットから取る。
- OCIR のリポジトリは Terraform で作らない。デプロイが、ビルドするサービスのリポジトリが無ければ基盤のコンパートメントに作る。本体の destroy では消えない。
- OCIR へのログインは、ローカルも VM も、使うたびに OCI の資格から短い期限のトークンを取って行う。auth token は使わない。
- Terraform のスタックは 2 つ。中はどちらもモジュールで分ける。
  - **base**: Terraform の destroy で消せないもの（コンパートメント・Vault・Vault のキー）と、作り直すと OCI の外の設定を直す要が出るもの（公開 DNS のゾーン。親のゾーンが NS レコードで委任する）だけ。
  - **本体**: それ以外のすべて（ネットワーク・NLB・Bastion・HeatWave・シークレット・バケット・DNS のレコードなど）。本体の destroy の前に、バケットを空にする。
  - 本体は、base のリソースを名前で探す。スタックの間で値を受け渡す仕組みは作らない。
  - 本体のシークレットの名前には、作るたびに変わるサフィックスを付ける。
- **基盤の開発中は、削除を防ぐ仕組みを一切付けない**（Terraform の `prevent_destroy`・HeatWave の削除防止・コンパートメントを消せなくする設定）。
- Terraform の state は Resource Manager が預かる。ローカルに state を置かない。
- 環境ごとの値（プロジェクトの一覧・DNS のゾーン・通知のメールの宛先・OCID など）は、この公開リポジトリに置かず、別の非公開の設定に置く。
- 基盤が作る OCI のリソースの名前は `<種類>-afp-<識別子>` にする（例: `bucket-afp-deploy`・`subnet-afp-db`・`trigger-afp-<プロジェクト>`）。識別子は必ず付け、1 つしか無いものは `main`。OCIR のリポジトリは `repo-afp-<プロジェクト>/<サービス>`。名前に英数字しか使えない Bastion は、ハイフンを除く（`bastionafpmain`）。

## 4. 状態の置き場所

VM の中には失って困るものを置かない。

| 状態 | 置き場所 |
|---|---|
| アプリのデータ | MySQL HeatWave |
| シークレット | OCI Vault |
| どのプロジェクトをどのドメインで動かすか | `bucket-afp-deploy`（Terraform が書く） |
| 各プロジェクトの今のバージョン | `bucket-afp-deploy`（デプロイのたびに、コンテナを起動する前に `afp` が書く） |
| イメージ | OCIR |
| リリースのファイル | `bucket-afp-deploy`（デプロイがバージョンごとに置く） |
| 基盤のコード | `bucket-afp-deploy` の `platform.tar.gz`（管理者のローカルのコードを、そのまま `make platform` が置く。§5.6） |
| DB のダンプ | `bucket-afp-dumps`（28 日で消える。§5.3） |
| HTTPS の証明書 | VM の中。消えたら Caddy が自動で取り直す |
| アプリのログ | OCI Logging（30 日。§5.11）。VM の中の Docker のログも残るが、VM を作り直すと消える |
| `afp` の操作のログ | `bucket-afp-logs`（28 日で消える） |

VM が消えたときは、Terraform で作り直すだけで戻る。

```mermaid
sequenceDiagram
  participant T as Terraform
  participant V as 新しい VM
  participant S as Object Storage・Vault・OCIR
  T->>V: 作る（NLB の行き先を新しい VM にする）
  V->>V: cloud-init: Docker と基盤のコードを入れる
  V->>S: プロジェクトの一覧と各プロジェクトの今のバージョンを読む
  loop プロジェクトごと
    V->>S: シークレットを読む・イメージを pull
    V->>V: 起動（DB は VM の外なのでそのまま）
  end
  V->>V: Caddy が証明書を取り直す
```

- 外から見える IP は NLB のものなので、VM だけを作り直したときは DNS は変わらない。本体のスタックを作り直して NLB の IP が変わったときも、本体が DNS のレコードを新しい IP に向ける（§5.4）。

## 5. 主な決定

### 5.1 相乗り

- 少ない VM と 1 つの DB に、全プロジェクトを相乗りさせる。VM が落ちると全プロジェクトが止まる。

### 5.2 VM

- OCI Compute の VM の上で Docker を使う。OS は Oracle Linux 9。
- VM は、取れるときは A1（1 OCPU・6 GB）、取れないときは E2.1.Micro にする。どちらにするかは、管理者が Terraform の変数で決める。A1 が取れずに作れなければ、変数を替えて再実行する。自動では切り替えない。
- A1 は arm64、E2.1.Micro は amd64。イメージは、そのときの VM の CPU の種類向けにだけビルドする。VM の CPU の種類を替えたら、デプロイしてある全プロジェクトをビルドし直す。
- VM にはスワップを置く。kdump は使わない（カーネルが落ちたときの記録のために、メモリを取っておかない）。
- アイドル回収は、作り直せば戻ることで備える（§4）。わざと負荷をかけて避けることはしない。
- `release` ブランチへの push からのデプロイでは、VM がその場でビルドし、イメージを OCIR に置く。前のバージョンへのロールバックと、VM を作り直したあとの起動では、ビルドせず OCIR から取る。ローカルからのデプロイは、ローカルでビルドする。

### 5.3 DB

- MySQL HeatWave の Always Free を、全プロジェクトで共有する。ローカルでは公式の `mysql` のコンテナを本番と同じバージョン・同じ設定で動かす。
- HeatWave の Always Free は保守のたびに最新のバージョンへ上がるので、ローカルのバージョンを追いかける。
- HeatWave の Always Free の自動バックアップ（保持 1 日で変えられない）は、そのまま使う。それを補うため、基盤がダンプを取る。
  - **週 1 回、毎週日曜 18:00 UTC（日本時間の月曜 3:00）** に、VM の systemd の timer（`afp install` が置く）が、全プロジェクトのダンプを取る（`afp backup`）。1 つが失敗しても残りを取り、最後に失敗で終わる。
  - デプロイの直前にも、そのプロジェクトのダンプを取る。
  - ダンプは `bucket-afp-dumps` に置き、ライフサイクル・ポリシー（Object Storage が決まった日数で消す規則）で 28 日で消す。週 1 回のダンプは 4 世代残る。デプロイの直前のダンプも 28 日で消える。
  - 全プロジェクトのダンプの成否を、Monitoring のメトリクス（成功で 1、失敗で 0）として送る。0 になるとアラームが、デプロイの成否と同じ通知のトピックにメールする。ダンプが動かなかったこと（VM の停止・timer が動かない）は、これでは分からない。
  - 戻すときは、ダンプを DB にリストアする（手順は wiki）。
- 基盤が 1 時間ごとに問い合わせる（§5.7 の `afp check-db`）。

### 5.4 入口とネットワーク

- VCN のサブネットを、役目ごとに 4 つに分ける。
  - **パブリック**: NLB だけを置く。外から入れるのはここだけ。
  - **VM 用**（プライベート）: VM。公開 IP を持たない。外へは NAT ゲートウェイ（外へ出るだけの出口）から、OCI のサービスへはサービス・ゲートウェイ（インターネットを通らない出口）から出る。
  - **DB 用**（プライベート）: MySQL HeatWave。VM と Bastion の接続口からの MySQL だけを受ける。
  - **Bastion 用**（プライベート）: Bastion の接続口（§5.9）。VM の ssh と DB の MySQL にだけ出られる。
- 入口は、VM ごとに 1 つの NLB（L4）。TCP の 80 番と 443 番を VM の同じ番号へ通す。TLS は解かず、利用者の IP を保持したまま渡す。NLB は Always Free に入っている（[references/oci-network-load-balancer.md](references/oci-network-load-balancer.md)）。
- Caddy を 1 つ置き、ドメイン名（TLS の SNI と HTTP の Host ヘッダ）でプロジェクトに振り分ける。パスでは分けない。
- 基盤が公開 DNS のゾーンを 1 つ持つ（OCI DNS）。プロジェクトのドメインは `<プロジェクトの名前>.<ゾーン>` に決まる。ゾーンの外のドメインは扱わない。
- 本体のスタックが、プロジェクトごとに A レコードを作り、そのプロジェクトの VM の前の NLB の公開 IP に向ける。NLB の IP は予約しない（NLB を作り直さない限り変わらず、変わればレコードも本体が直す）。親のゾーンからの委任（NS レコード）は、管理者が最初に一度だけ行う。
- DNS の問い合わせには料金がかかる（Always Free に入っていない。ゾーンそのものは無料）。
- **80 番は常に全体に開ける**。443 番は、全体に開けるか、決めた IP からだけにするかを切り替えられる。絞るのは入口（パブリック・サブネット）で、VM は NLB を通ったものだけを受ける。

### 5.5 シークレット

- プロジェクトに渡す値は 3 種類に分ける。
  - **設定値**（秘密でないもの）: 非公開の設定に、値をそのまま書く。Vault を通さない。
  - **生成するシークレット**: Terraform が生成して Vault に置く。
  - **手で作るシークレット**（外から持ってくる秘密の値）: 管理者が Vault に手で作り、非公開の設定にはその OCID だけを書く。Terraform は作らない。
- **Terraform が作ったものを、人やスクリプトがあとから上書きすることはしない**。GitHub のトークンも手で作るシークレットにする。webhook の Secret は、トリガーと一緒に `make apply` の中のスクリプトが作り、トリガーと一緒に消す。
- 手で作るシークレットは、基盤の Vault の、基盤のコンパートメントに置く。本体のスタックを作り直しても残る。
- VM はシークレットをインスタンス・プリンシパル（VM そのものに与える権限）で読み、設定値と一緒に、`docker compose` を起動するプロセスの環境変数として渡す。環境変数のファイルは作らない。
- **コンテナからは、VM のメタデータ（`169.254.169.254`）への通信を、VM の初期設定で落とす**。同じ IP の 53 番（VCN の DNS）だけは通す。メタデータの古いエンドポイント（v1）も止める。

### 5.6 デプロイ

- デプロイは、管理者がローカルから行う（`make deploy`）か、自動で行う。
- ローカルからのデプロイは、プロジェクトのディレクトリをそのまま使い、git を前提にしない（コミットやタグが無くてよい）。バージョン名は、指定しなければ UTC の時刻（例: `20261124T012345Z`）、指定すればその名前。同じ名前を指定すれば上書きする。
- 自動のデプロイでは、**プロジェクトのリポジトリ** の `release` ブランチに push すると、そのプロジェクトだけをビルドし、VM でデプロイするところまで自動で行う。デプロイしたバージョン名は、`release` の先頭のコミットに付いた `v` で始まるタグ（例: `v1.2.3`）の名前そのもの。そのようなタグが無い、または複数あるときは、デプロイしない。
- パイプラインは、プロジェクトの一覧でリポジトリを伝えたプロジェクトにだけ作る。伝えないプロジェクトは、管理者がローカルからデプロイする（下の「DevOps が使えないとき」と同じ方法）。伝えるかは、あとから変えられる。
- **基盤のコードは、git とタグに頼らずに VM に届ける**。`make platform` が、管理者のローカルのコードをそのまま（コミットしていなくても）アーカイブして Object Storage に置き、VM はそれを取って入れ替える。自動のデプロイのビルドも、そこから基盤のスクリプトを取る。基盤のリポジトリのタグは、管理のために任意で付けるもので、デプロイには関係しない。
- 入れ替えるのは、VM の起動のたびと、管理者が Run Command で呼んだときに実行される起動スクリプト（`afp` の外の固定のスクリプト）で、`afp` 自身は入れ替えない。起動スクリプトそのものは、VM を作り直したときに入る。
- VM でデプロイを実行するのは、DevOps の **インスタンス・グループへのデプロイ**。VM の中の **Oracle Cloud Agent**（OCI のイメージに入っているエージェント）の **Run Command** のプラグインが、`afp deploy <プロジェクト> <バージョン>` を実行する（[references/oci-devops.md](references/oci-devops.md)・[references/oci-run-command.md](references/oci-run-command.md)）。
- DevOps が使えないときは、ローカルから同じ Run Command を直接呼んで `afp deploy` を実行させる。
- デプロイには ssh を使わない。

OCI DevOps のうち、共有するものとプロジェクトごとのものは次のとおり。

| 共有する（基盤が1つだけ持つ） | プロジェクトごと（リポジトリを伝えたプロジェクトに、`make apply` が作る） |
|---|---|
| DevOps のプロジェクト（パイプラインをまとめる単位） | ビルドのパイプライン・デプロイのパイプライン |
| GitHub への接続（非公開のリポジトリを読むためのトークンは基盤で 1 本。管理者が手で作るシークレット） | トリガー（どのリポジトリの、`release` への push で動くか）と webhook の Secret（Vault。トリガーと一緒に作り、一緒に消す） |
| 通知の宛先（成否のメール） | イメージとリリースのファイルの保存先 |
| DevOps に与える OCI の権限 | — |

- トリガーと webhook の Secret だけは Terraform で作らず、`make apply` の中で OCI CLI が作る・消す・絞りを直す（Terraform では webhook の Secret が得られないため）。`make apply` で設定どおりになり、`make destroy` で消えるのは、ほかのリソースと同じ。
- GitHub の側の webhook は、パイプラインを作ったときに、管理者が GitHub の画面で登録する。URL は `make apply` が表示し、Secret は Vault からコピーする。
- **パイプラインはプロジェクトごとに独立させる**。あるプロジェクトの push は、そのプロジェクトのパイプラインだけを動かす。
- ビルドは、プロジェクトの間で並んで走ってもよい。
- VM の上のデプロイは、1 つずつ行う（`afp` がロックを取る）。後のものは前のものが終わるのを待つ。
- リポジトリを伝えたプロジェクトは、基盤の雛形に沿った DevOps のビルドの手順（`build_spec.yaml`）を、自分のリポジトリに置く。雛形の決まった部分が、そのバージョンのソースと `compose.afp.yaml` を Object Storage に置き、VM の `afp deploy` がそれをビルドしてデプロイする。プロジェクトは、決まった部分の前に自分の手順を足せる。

### 5.7 基盤の監視

基盤の管理者が知りたいことを、OCI Monitoring のアラームで見る。送り先は、どれもデプロイの成否と同じ通知のトピック（`topic-afp-devops`）。

| 知りたいこと | アラーム | 見るもの | 鳴るとき |
|---|---|---|---|
| 利用者が外からアプリに届くか（VM が止まった、Caddy が落ちた） | `alarm-afp-nlb-unhealthy` | NLB が 80・443 番にしている TCP のヘルスチェックの結果 | 5 分続けて失敗 |
| DB が動いているか | `alarm-afp-check-db` | `afp check-db` が 1 時間ごとに送る `afp/check_db_ok`（`SELECT 1` に答えたら 1） | 直近 1 時間に 0 がある |
| VM のメモリ | `alarm-afp-vm-memory` | Oracle Cloud Agent の監視のプラグインが送る `MemoryUtilization` | 5 分の平均が 90% を超え、5 分続く |
| VM のディスク | `alarm-afp-vm-disk` | `afp check-disk` が 1 時間ごとに送る `afp/disk_used_percent`（`/` の使用率） | 直近 1 時間に 90% を超えた |
| 週 1 回のダンプが取れたか | `alarm-afp-backup` | §5.3 | 失敗した |

- `afp check-db` と `afp check-disk` は、VM の systemd の timer（`afp install` が置く）が 1 時間ごとに動かす。ロックは取らない。ログは、失敗したときだけバケットに置く。
- 分からないこと：アプリが正しく動いているか（TCP のヘルスチェックなので、アプリが 502 を返しても分からない）、証明書が切れたこと、timer だけが止まったこと。
- アプリの監視は各プロジェクトの責任とし、基盤は用意しない。

### 5.8 `afp`

- Python で書き、サブコマンドは `argparse` で作る。外部のライブラリは使わない（OCI の SDK も使わない）。VM の OS の標準の python3（3.9）で動かす。
- OCI のサービスは OCI CLI を、コンテナは `docker compose` を、DB は `mysql` のクライアントを、`subprocess` から呼ぶ。
- 使い方は `--help` に置く。

### 5.9 ローカルからの保守

- Bastion の接続口は、Bastion 用のサブネットに置く（§5.4）。
- ローカルから DB に入るときは、OCI Bastion のポート転送を使う（[references/oci-bastion.md](references/oci-bastion.md)）。セッションの SSH 鍵は、そのたびに作って捨てる。
- ローカルから VM に ssh で入るのは保守のときだけで、Bastion の Managed SSH のセッションを使う。SSH 鍵はそのたびに作って捨て、VM に固定の SSH 鍵を置かない。22 番は外に開けない。

### 5.10 バケット

- 基盤のバケットは、役目ごとに 3 つ。

| バケット | 中身 | 消す規則 | VM の権限 |
|---|---|---|---|
| `bucket-afp-deploy` | プロジェクトの一覧（`afp.json`）・各プロジェクトの今のバージョン・リリースのファイル・基盤のコード | 無し | 読み書き |
| `bucket-afp-dumps` | DB のダンプ（`<プロジェクト>/<UTC の時刻>[-before-<バージョンのタグ>].sql.gz`） | 28 日で消す | 新しく置くことだけ |
| `bucket-afp-logs` | `afp` の操作のログ（`<UTC の時刻>-<操作>[-<プロジェクト>].log`。操作 1 回で 1 ファイル） | 28 日で消す | 新しく置くことだけ |

- VM の権限を「新しく置くことだけ」に絞れているかは、未確認。

### 5.11 アプリのログ

- アプリは、ログを標準出力・標準エラーに出す。VM の中の Oracle Cloud Agent（Custom Logs Monitoring のプラグイン）が、Docker のログのファイルを読み、OCI Logging に送る。
- 送り先は、ロググループ `loggroup-afp-apps` のログ `log-afp-apps` の 1 つ。**全プロジェクトのログを 1 つのログにまとめ、プロジェクトごとには分けない**。保存は 30 日。見るときは、検索でプロジェクトの名前で絞る。
- どのプロジェクトのログかを見分けるため、`afp install` が Docker の設定に、各行へ compose のプロジェクトとサービスの名前を入れる設定（`labels`）を書く。
- ログを読める人は、全プロジェクトのログを読める（[01](01_purpose.md) §4 の前提による）。
- VM の中の Docker のログ（10 MB × 3）も残る。
- VM の権限は、コンパートメントの中のログに送れること。ロググループでは絞らない。

### 5.12 作らないもの

- 既製の PaaS（Dokku・Coolify など）・Kubernetes・Nomad
- 共通のログイン（SSO）。各アプリが自分でログインを持つ
- 自前の監視の仕組み（Prometheus など）
- ステージング環境
- 頻度の低いことを自動で監視する仕組み（DB のバージョンのずれの検出・A1 の取り直しなど）
