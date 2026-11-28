# 開発者向けの文書

基盤そのものを作る人向けの文書。基盤を使う人（基盤の管理者・プロジェクトの管理者）向けの使い方としくみは、wiki にある。

## 番号の付いた文書

前から順に読む。

| 文書 | 内容 |
|---|---|
| [01 目的と方針](01_purpose.md) | なぜこの基盤があるのか、何を優先するのか、向く使い方と向かない使い方 |
| [02 構成と決定](02_architecture.md) | 前提にした無料枠、全体の構成、主な決定 |
| [03 役割と責任](03_responsibilities.md) | 基盤の管理者とプロジェクトの管理者の分担と境目 |
| [04 基盤を使う](04_using.md) | プロジェクトの管理者向け。基盤にデプロイするための約束 |

決定の理由と採らなかった案は、`adr/` にある。

## 参考資料

それだけで読める、独立した資料。

| 資料 | 内容 |
|---|---|
| [OCI の無料枠](references/oci-free-tier.md) | Always Free の枠・制約・アイドル回収（確かめた日付と出典つき） |
| [MySQL でアプリを書くときの注意](references/mysql-notes.md) | ほかの DB（PostgreSQL など）との違い、日本語の照合順序、HeatWave のバージョンの上がり方 |
| [OCI Bastion](references/oci-bastion.md) | プライベート・サブネットのリソースにローカルから入る方法（ポート転送） |
| [OCI Resource Manager](references/oci-resource-manager.md) | Terraform を OCI の側で実行するサービスの使い方と癖 |
| [OCI Vault](references/oci-vault.md) | キーとシークレットの削除待ちと、それが削除に与える影響 |
| [OCI DevOps](references/oci-devops.md) | VM へのデプロイ（インスタンス・グループ・Run Command）の仕組みと制約 |
| [OCI の Run Command](references/oci-run-command.md) | VM の中のエージェントにコマンドを実行させる仕組み、届くまでの時間と制限 |
| [OCI の Compute の VM](references/oci-compute-vm.md) | Oracle Linux 9 の小さな VM（E2.1.Micro・A1）で分かったこと（kdump の予約・dnf・firewalld・エージェント） |
| [OCI Network Load Balancer](references/oci-network-load-balancer.md) | L4 で受けて TLS を解かずに後ろへ渡すロードバランサー。組み立てと、送信元 IP の保持 |
| [OCIR](references/oci-registry.md) | OCI のコンテナ・レジストリ。名前の決まり、ログイン、受け付けられなかったイメージの形 |
