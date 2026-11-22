# OCI DevOps: ビルドと VM へのデプロイ

OCI DevOps は、ビルドとデプロイのパイプラインを動かすサービス。AWS の CodePipeline・CodeBuild・CodeDeploy を 1 つにしたものに当たる。ここでは、ビルドの段と、Compute の VM にデプロイする仕組みをまとめる。

- **確かめた日**: 2026-11-10・2026-11-15・2026-11-19（Oracle の公式文書。2026-11-15 に一部を動かして確かめた。動かした結果はそう明記する）

## 1. 仕組み

| OCI | AWS で近いもの | 内容 |
|---|---|---|
| インスタンス・グループへのデプロイ | CodeDeploy（EC2 へのデプロイ） | デプロイのパイプラインの段の 1 つ。対象の VM の集まり（インスタンス・グループの環境）に、決めたコマンドを順に実行させる |
| デプロイの構成のファイル | `appspec.yml` | YAML。`version: 1.0`・`component: deployment`。`files`（成果物をどこに置くか）と `steps`（実行するコマンド）を書く |
| Oracle Cloud Agent | SSM のエージェント・CodeDeploy のエージェント | OCI のイメージに入っているエージェント。プラグインで機能を足す |
| Run Command（Compute Instance Run Command のプラグイン） | SSM の Run Command | VM でコマンドを実行させる。DevOps のデプロイはこれを使う。CLI からも直接呼べる（`oci instance-agent command create`） |

## 2. 制約

- **対応する OS は Oracle Linux と CentOS だけ**（"DevOps only supports instance group deployments to Oracle Linux and CentOS."）。
- VM で Run Command のプラグインを有効にし、動いている必要がある。有効にしてから効くまで最大 10 分。
- デプロイの構成のファイルは、DevOps の成果物として直接書ける（inline）か、Artifact Registry に置く。それ以外の成果物は inline にできない。
- `steps` のコマンドは、既定では `ocarun` というユーザで動く。ステップごとに `runAs` で別のユーザ（`root` など）を指定できる。時間の上限も決められる（`timeoutInSeconds`）。
- 複数行のコマンドは、既定では途中で失敗しても止まらない。止めるには `set -e` を書く。
- `onFailure` に失敗したときの片付けを書けるが、段の結果（失敗）は変わらない。
- 権限: デプロイのパイプラインに、VM でコマンドを実行させる IAM の権限が要る。
- Run Command そのものの制限（同時に動くのは既定で 2 つ・受け取って残せるのは 5 つまで）と、命令を取りに来る間隔（既定で約 4 分）は [oci-run-command.md](oci-run-command.md)。インスタンス・グループへのデプロイでも同じ間隔で待つのかは未確認。

## 3. ビルドの段とトリガー

- **トリガーの出来事**（GitHub などの外のリポジトリ）: Push・Pull Request Created・Updated・Merged・Reopened。Push では、ブランチの名前と、含める・除くファイルの glob で絞れる。**タグの push を出来事として選べる・タグの名前で絞れるという記述は無い**（[Triggering a Build Run](https://docs.oracle.com/en-us/iaas/Content/devops/using/trigger_build.htm)）。
- **GitHub への接続**: GitHub の Personal Access Token を Vault のシークレットに入れ、接続はそのシークレットを指す。文書の手順は classic のトークンで、非公開のリポジトリを読むには「Full control of private repositories」（`repo`）を付けるとされる。fine-grained のトークンの記述は無い（[Build Source Integration](https://docs.oracle.com/en-us/iaas/Content/devops/using/getting_started.htm)）。
- **GitHub のトークンのシークレットの base64 に改行が入っていると、DevOps はトークンを使えない**。
  - 症状: 接続の検証が `500 InternalError`（「Unknown Error. Unable to validate the connection」）。ビルドは、ビルドの段に入る前に失敗する（「Internal Error fetching build spec file, please try again.」。監査ログの `GetGitFileContent` が 500）。シークレットは読めている（監査ログの `GetSecretBundle` が 200）。
  - 改行が入る道筋: CLI の `oci vault secret update-base64` は、`--secret-content-content` に渡した base64 を改行ごと預かる。GNU coreutils の `base64` は、既定で 76 文字ごとに改行を入れる（[base64 invocation](https://www.gnu.org/software/coreutils/manual/html_node/base64-invocation.html)。macOS に元からある `base64` は入れない）。fine-grained のトークン（93 文字）の base64 は 76 文字を超えるので改行が入り、classic のトークン（40 文字）では入らない。
  - 改行が無ければ、fine-grained のトークン（対象のリポジトリだけ・Contents と Metadata の読み取りだけ）で、接続の検証とビルドでの取得の両方が通る。
- fine-grained のトークンの対象のリポジトリは、作ったあとで GitHub の画面で編集して足せる。トークンの値は変わらない。
- 権限が足りないときは、`RelatedResourceNotAuthorizedOrNotFound`（監査ログでは `GetGitFileContent` の 404）になる。Troubleshooting のページ（[Troubleshooting DevOps](https://docs.oracle.com/en-us/iaas/Content/devops/using/troubleshooting.htm)）に、上の 500 の症状は無い。
- GitHub の webhook の Content type が既定の `application/x-www-form-urlencoded` のままだと、トリガーの URL は `400`（`InvalidParameter`・「Unable to parse message body」）を返す（2026-11-15。ping で確かめた）。`application/json` にすると通った。
- **GitHub のタグの push からは、ビルドできない**（2026-11-19）:
  - トリガーの絞り（`headRef`）は、ブランチの名前（例: `release`。`refs/heads/` は付けない）で、そのブランチへの push に合う。
  - タグの push は、`refs/tags/<名前>` を全部書いたときだけ合った。`refs/tags/v*`・`v*` では合わなかった（`*` がワイルドカードとして効くかは未確認）。GitHub からの知らせは、合わないときも受け付けられる（202）。
  - タグの push でビルドが始まっても、DevOps はタグの ref をブランチの名前として取りに行き、「Remote branch refs/tags/<名前> not found in upstream origin」でソースの取得に失敗する。`build_spec.yaml` の手順に入る前。
- ブランチの push からのビルドでは、取ったリポジトリに、そのコミットに付いたタグも入っている（`git tag --points-at HEAD` で見える。2026-11-19）。ブランチとタグを 1 回の push（`git push --atomic`）で送ったときも、タグは入っていた（1 回試した。2026-11-19）。
- トリガーの絞りは、`oci devops trigger update-github-trigger` で変えられる。トリガーの URL と webhook の Secret は変わらない（2026-11-19）。
- **webhook**: GitHub のトリガーは、GitHub の側に webhook と秘密の文字列を設定しなければならない。中身の形式は `application/json`。トリガーの URL と秘密の文字列は、コンソールでトリガーを作ったときに一度だけ表示され、あとから取り出せない（[Triggering a Build Run](https://docs.oracle.com/en-us/iaas/Content/devops/using/trigger_build.htm)）。Terraform の `oci_devops_trigger` が出す属性は `trigger_url` までで、秘密の文字列は無い（[プロバイダの文書](https://registry.terraform.io/providers/oracle/oci/latest/docs/resources/devops_trigger)。2026-11-15）。
- **webhook の秘密の文字列（Secret）を API で得られるのは、作成の応答だけ**: SDK の型で、`secret` があるのは作成の応答の `GithubTriggerCreateResult` だけ。取得の `GithubTrigger`・一覧の `GithubTriggerSummary` には無い（[oci-go-sdk の devops](https://github.com/oracle/oci-go-sdk/tree/master/devops)）。作り直す API も無い（CLI 3.96.0 の `oci devops trigger` の命令の一覧）。
- **Terraform で作ると Secret は得られない**: プロバイダ 9.12.1 は、作成の応答から ID だけを取り、取得の API で読み直して state に書く（[devops_trigger_resource.go](https://github.com/oracle/terraform-provider-oci/blob/master/internal/service/devops/devops_trigger_resource.go)）。要望の issue [#1681](https://github.com/oracle/terraform-provider-oci/issues/1681) は 2022-10 から開いたまま（2026-11-15）。
- CLI の `create-github-trigger` は、作成の応答を出力する。`--wait-for-state` を付けると、出力は作業の進み具合（work request）になる（CLI の `--help`。Secret が出なくなる見込み。未確認）。
- **ビルドの実行環境**（build runner）: Oracle Linux 8 のコンテナ。入っている道具に OCI CLI 3.58.1・Git 2.48.1・Python 3.11.11・**Podman 4.9.4**（Docker でなく）がある。版は変わりうる（[Build Runner Runtime Details](https://docs.oracle.com/en-us/iaas/Content/devops/using/runtime_details.htm)）。`sudo` は使えない（[Build Specification](https://docs.oracle.com/en-us/iaas/Content/devops/using/build_specs.htm)）。
- **実行環境を動かして調べた結果**（2026-11-15。イメージ `OL8_X86_64_STANDARD_10`・既定の大きさ）:
  - CPU は `x86_64`。OS は Oracle Linux 8.10。手順は root（uid 0）で動き、Podman 4.9.4 も root で動く（rootless でない）。
  - arm64 のエミュレーションは使えない: `/proc/sys/fs/binfmt_misc` は空で、qemu を登録しようとすると（`podman run --privileged docker.io/tonistiigi/binfmt --install arm64`）「cannot mount binfmt_misc filesystem」「operation not permitted」。arm64 のコンテナは `Exec format error` で動かない。
  - ビルドのパイプラインのパラメータは、手順の環境変数として届く。手で始めた実行では、`OCI_TRIGGER_*` は空。
  - 手で始めた実行で、`build_spec.yaml` を読んでから最後の手順が終わるまで、約 2 分 15 秒（イメージの pull を 2 回含む）。
- デプロイのパイプラインの Shell の段（コンテナ・インスタンスでコマンドを動かす）に入っている道具は、bash・Git・OCI CLI・kubectl・Terraform・Helm・JDK・Python・SQLcl。Podman・Docker は無い。形を選べるが、arm64 の形を選べるかの記述は無い（[Shell Container Image Runtime Details](https://docs.oracle.com/en-us/iaas/Content/devops/using/shellruntime_details.htm)・[Adding a Shell Stage](https://docs.oracle.com/en-us/iaas/Content/devops/using/shell_stage.htm)）。
- 実行環境の大きさは、既定が 2 OCPU・8 GB。変えられるが、用意に時間がかかる。**CPU の種類（arm64 が選べるか）の記述は無い**（[Managed Build Stage](https://docs.oracle.com/en-us/iaas/Content/devops/using/managed_buildstage.htm)）。
- **料金**: 「ビルドの間に使った実行環境（OCPU とメモリ）の分を課金する」（同上）。単価は確かめていない。
- ビルドの手順のファイル（`build_spec.yaml`）の `outputArtifacts` に `DOCKER_IMAGE` を書くと、手順の中で作ったイメージを成果物として次の段に渡す。`env.exportedVariables` の値は、同じパイプラインのあとの段で使える（[Build Specification](https://docs.oracle.com/en-us/iaas/Content/devops/using/build_specs.htm)）。
- **資源の説明（description）**: HTML のタグに見える文字（`<` と `>` で囲んだもの）を含むと断られる（2026-11-15）。ビルドの段は、作るときは説明を省けるが、そのあとの更新では空の説明が送られ、`400 InvalidParameter`（「Invalid description」）で断られる（2026-11-19）。
- **インスタンス・グループへのデプロイの、VM の上の作業ディレクトリ**: エージェント（Run Command のプラグイン）は、デプロイごとに `/var/lib/ocarun/commands/wd/<デプロイの OCID>` を作り、コマンドをそこで動かす。新しいデプロイを始めるとき、前のデプロイのディレクトリを、まだ動いていても消す。消されたほうのコマンドは、今いるディレクトリが無くなる（2026-11-22。続けて 2 つデプロイしたときに、エージェントのログで確かめた）。

## 4. 未確認

- 成果物を Artifact Registry に置かず、デプロイの構成のファイルだけを inline で書いて動くか（コマンドが自分で成果物を取りに行く形）。
- インスタンス・グループへのデプロイに料金がかかるか。
- ブランチとタグを別々に push したとき、ビルドがソースを取るまでにタグが届いているか（届かなければ、版の名前が見つからない）。
- 前のデプロイの作業ディレクトリが消されたあと、そのデプロイのコマンドが成功したとき、DevOps がそのデプロイを成功と扱うか（エージェントは、消えたディレクトリの片付けとログの送り出しに失敗する）。
- 手で始めたビルド（ビルドのソースの既定のブランチを取る）が、トリガーからのビルドと同じに動くか。

## 5. 出典

- [Deploying to an Instance Group](https://docs.oracle.com/en-us/iaas/Content/devops/using/deploy_instancegroups.htm)（対応する OS・プラグイン・成果物）
- [Deployment Configuration File](https://docs.oracle.com/en-us/iaas/Content/devops/using/deployment_specs.htm)（構成のファイルの書き方・`ocarun`・`set -e`）
- [Triggering a Build Run](https://docs.oracle.com/en-us/iaas/Content/devops/using/trigger_build.htm)・[Managed Build Stage](https://docs.oracle.com/en-us/iaas/Content/devops/using/managed_buildstage.htm)・[Build Runner Runtime Details](https://docs.oracle.com/en-us/iaas/Content/devops/using/runtime_details.htm)・[Build Specification](https://docs.oracle.com/en-us/iaas/Content/devops/using/build_specs.htm)（ビルドとトリガー）
- [Build Source Integration](https://docs.oracle.com/en-us/iaas/Content/devops/using/getting_started.htm)（GitHub のトークンと Vault）
- [Running Commands on an Instance](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/runningcommands.htm)（Run Command）
