# 024 GitHub のトリガーは、Terraform でなく `make apply` の中で作る。パイプラインはリポジトリを伝えたプロジェクトにだけ作る

- 決めた日: 2026-11-15

## 背景

OCI DevOps で GitHub への push からビルドを始めるには、DevOps の側にトリガー（GitHub からの知らせを受ける窓口。専用の URL を持つ）を作り、GitHub の側にその URL への webhook を登録する。知らせが本物の GitHub から来たかを確かめるため、両方に同じ webhook の Secret を置く。GitHub はこれを鍵に知らせの署名（HMAC-SHA256）を作り、DevOps は自分の Secret で確かめる。Secret が合わない知らせは受け付けられない。

Secret は、トリガーを作るときに OCI が決める。API がそれを返すのは、作成の応答（`GithubTriggerCreateResult`）の 1 回だけで、取得の応答（`GithubTrigger`）には無い。作り直す API も無い（[references/oci-devops.md](../references/oci-devops.md)）。

Terraform の OCI のプロバイダ（9.12.1）は、作成の応答から ID だけを取り、取得の API で読み直して state に書く。そのため、Terraform でトリガーを作ると Secret は state にも output にも残らず、誰も得られない。プロバイダの issue（[#1681](https://github.com/oracle/terraform-provider-oci/issues/1681)）は 2022 年から開いたまま。公開の Terraform を調べても（2026-11-15。`oci_devops_trigger` を使う 17 件）、Secret を Terraform で扱う例は無かった。

また、プロジェクトには手元からのデプロイ（`make deploy`）もあり、パイプラインが無くても載せられる。

## 決定

- 基盤の操作は「設定ファイル（非公開のプロジェクトの一覧）を書いて `make apply`」にまとめる。`make apply` で設定どおりになり（何度流しても同じ）、`make destroy` で全部消える。
- プロジェクトの受け入れ（DB・ユーザ・シークレット・振り分け）と、パイプラインを作るかを分ける。一覧の項目にリポジトリを書いたプロジェクトにだけ、パイプライン一式（ビルドとデプロイのパイプライン・トリガー・webhook の Secret）を作る。書かないプロジェクトは手元からデプロイする。
- トリガーだけは Terraform で作らず、`make apply` の中で OCI CLI が作る・消す（`scripts/triggers.py`）。
  - トリガーがあるかは、DevOps のプロジェクトのトリガーの一覧を直接見て決める。名前は `afp-<プロジェクト>`。
  - 作成の応答の Secret は、プロジェクトごとの Vault のシークレット（Terraform が仮の値で作り、中身は変えない）に新しい版として入れる。画面・ファイル・ログには出さない。入れられなければ、そのトリガーを消す。
  - トリガーの中身（push・タグの絞り）は基盤で固定し、設定に置かない。
  - `make destroy` は、destroy の前にトリガーを消す。
- GitHub の webhook の登録は、パイプラインを作った最初に、基盤の管理者が GitHub の画面で行う。URL は `make apply` が表示し、Secret は Vault からコピーする。

## 理由

- Terraform で作ると、トリガーは動かない（Secret が得られない）。
- `make apply` の中で作れば、パイプライン一式が 1 つのコマンドでそろう。トリガーを別のコマンドにすると、一式を 2 つの操作に割ることになり、片方を忘れると半端な状態が残る。
- 判定に Vault を使うと、Terraform が仮の値で作るので常に「ある」になり、トリガーを手で消したときにずれる。実物の一覧を見ればずれない。
- Secret を Vault に置けば、リポジトリを移した・webhook を消したなど GitHub の側だけやり直すときに、トリガーを作り直さずに貼り直せる。画面に出さないので、`make apply` を誰が流しても Secret を見ずに済む。
- webhook の登録はまれ（パイプラインを作るときと、本体を作り直したとき）なので、手作業でよい。

## 採らなかった案

| 案 | 理由 |
|---|---|
| Terraform でトリガーを作る | Secret が得られず、webhook が受け付けられない |
| CLI で作ったトリガーを、Terraform の `import` で state に取り込む | Terraform がトリガーを置き換える変更が入ると、新しいトリガーの Secret がまた捨てられ、webhook が知らせなく動かなくなる |
| トリガーを作る別のコマンド（`make webhook` など） | パイプライン一式を 2 つの操作に割る |
| Secret を画面に 1 回出すだけで、Vault に置かない | GitHub の側だけやり直すときに、トリガーを作り直すことになる。画面に出る |
| GitHub の CLI（`gh`）で webhook の登録まで行う | まれな作業のために、OCI の外の CLI・そのログイン・GitHub だけの処理という部品を増やす（基盤の方針の「『自動化』の名で部品を増やさない」に反する） |
| GitHub のリポジトリを DevOps のコードのリポジトリに写し（ミラー）、OCI の中のトリガーを使う | 写す間隔（既定で 15 分か 30 分。文書とプロバイダで食い違う）だけ遅れる。写した側のトリガーは新しいコミットで動くので、既にあるコミットへのタグの push で動かないおそれがある（ADR 015 と合わない） |
| 一覧の全プロジェクトにパイプラインを作り、使わないものは webhook を登録しないだけ | 受け入れとパイプラインという別のものを混ぜる。リポジトリの無いプロジェクトにも、使わない資源ができる |

## 引き換え

- トリガーは Terraform の state に無い。Terraform の plan には出ない。
- 本体を作り直すと、トリガーの URL と Secret が新しくなり、webhook を登録し直す。
