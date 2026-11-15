# OCI DevOps: ビルドと VM へのデプロイ

OCI DevOps は、ビルドとデプロイのパイプラインを動かすサービス。AWS の CodePipeline・CodeBuild・CodeDeploy を 1 つにしたものに当たる。ここでは、ビルドの段と、Compute の VM にデプロイする仕組みをまとめる。

- **確かめた日**: 2026-11-10・2026-11-15（Oracle の公式文書。まだ動かしていない）

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
- **webhook**: GitHub のトリガーは、GitHub の側に webhook と秘密の文字列を設定しなければならない。中身の形式は `application/json`。トリガーの URL と秘密の文字列は、コンソールでトリガーを作ったときに一度だけ表示され、あとから取り出せない（[Triggering a Build Run](https://docs.oracle.com/en-us/iaas/Content/devops/using/trigger_build.htm)）。Terraform の `oci_devops_trigger` が出す属性は `trigger_url` までで、秘密の文字列は無い（[プロバイダの文書](https://registry.terraform.io/providers/oracle/oci/latest/docs/resources/devops_trigger)。2026-11-15）。
- **ビルドの実行環境**（build runner）: Oracle Linux 8 のコンテナ。入っている道具に OCI CLI 3.58.1・Git 2.48.1・Python 3.11.11・**Podman 4.9.4**（Docker でなく）がある。版は変わりうる（[Build Runner Runtime Details](https://docs.oracle.com/en-us/iaas/Content/devops/using/runtime_details.htm)）。`sudo` は使えない（[Build Specification](https://docs.oracle.com/en-us/iaas/Content/devops/using/build_specs.htm)）。
- 実行環境の大きさは、既定が 2 OCPU・8 GB。変えられるが、用意に時間がかかる。**CPU の種類（arm64 が選べるか）の記述は無い**（[Managed Build Stage](https://docs.oracle.com/en-us/iaas/Content/devops/using/managed_buildstage.htm)）。
- **料金**: 「ビルドの間に使った実行環境（OCPU とメモリ）の分を課金する」（同上）。単価は確かめていない。
- ビルドの手順のファイル（`build_spec.yaml`）の `outputArtifacts` に `DOCKER_IMAGE` を書くと、手順の中で作ったイメージを成果物として次の段に渡す。`env.exportedVariables` の値は、同じパイプラインのあとの段で使える（[Build Specification](https://docs.oracle.com/en-us/iaas/Content/devops/using/build_specs.htm)）。

## 4. 未確認

- 成果物を Artifact Registry に置かず、デプロイの構成のファイルだけを inline で書いて動くか（コマンドが自分で成果物を取りに行く形）。
- インスタンス・グループへのデプロイに料金がかかるか。
- GitHub のタグの push でトリガーが動くか（§3）。
- fine-grained のトークン（対象のリポジトリだけ・Contents の読み取りだけ）で、非公開のリポジトリを読めるか（§3）。
- Terraform で作った GitHub のトリガーの、webhook の秘密の文字列をどこで得るか（§3）。
- 実行環境で arm64 のイメージを作れるか（Podman のエミュレーション。`sudo` が無いので binfmt を入れられない見込み）。

## 5. 出典

- [Deploying to an Instance Group](https://docs.oracle.com/en-us/iaas/Content/devops/using/deploy_instancegroups.htm)（対応する OS・プラグイン・成果物）
- [Deployment Configuration File](https://docs.oracle.com/en-us/iaas/Content/devops/using/deployment_specs.htm)（構成のファイルの書き方・`ocarun`・`set -e`）
- [Triggering a Build Run](https://docs.oracle.com/en-us/iaas/Content/devops/using/trigger_build.htm)・[Managed Build Stage](https://docs.oracle.com/en-us/iaas/Content/devops/using/managed_buildstage.htm)・[Build Runner Runtime Details](https://docs.oracle.com/en-us/iaas/Content/devops/using/runtime_details.htm)・[Build Specification](https://docs.oracle.com/en-us/iaas/Content/devops/using/build_specs.htm)（ビルドとトリガー）
- [Build Source Integration](https://docs.oracle.com/en-us/iaas/Content/devops/using/getting_started.htm)（GitHub のトークンと Vault）
- [Running Commands on an Instance](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/runningcommands.htm)（Run Command）
