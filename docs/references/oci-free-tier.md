# OCI の無料枠

OCI（Oracle Cloud Infrastructure）の無料枠を調べた結果。

- **確かめた日**: 2026-11-07（Oracle の公式文書）。予約済みの公開 IP・Cloud Guard・アイドル回収は 2026-11-13。MySQL HeatWave の管理者のパスワードの特殊文字は 2026-11-22。DNS は 2026-11-23。Network Load Balancer・NAT ゲートウェイ・サービス・ゲートウェイは 2026-11-25。Logging と、MySQL HeatWave の有料の種類の単価は 2026-11-26
- **無料枠は変わる**（2026-06 に A1 の枠が半分になった）。使う前に §6 の出典で確かめ直す。

## 1. 無料枠の種類

| 種類 | 内容 |
|---|---|
| Free Trial | 登録から 30 日間、一定額のクレジットで有料のサービスも試せる |
| **Always Free** | 期限なく無料で使えるリソース。Free Trial が終わっても残る。有料（PAYG: 従量課金）のアカウントでも使える |

## 2. Always Free の主なリソース

| リソース | 枠 |
|---|---|
| Compute: Ampere A1（`VM.Standard.A1.Flex`、Arm） | 月 1,500 OCPU 時間・9,000 GB 時間 ＝ 常時 **合計 2 OCPU・12 GB**。1台にまとめても、分けてもよい |
| Compute: E2.1.Micro（x86） | **2 台** まで。各 1/8 OCPU・1 GB |
| ブロック・ボリューム | ブートとブロックの **合計 200 GB**。バックアップ 5 個 |
| Object Storage | Always Free だけのアカウントで 20 GB。有料のアカウントでは種類（Standard・Infrequent Access・Archive）ごとに 10 GB。API 5 万回/月 |
| Vault | シークレット 150 個（各 40 版）。ソフトウェアで守る鍵は無制限（シークレットの暗号化にも使えた。2026-11-09 実測） |
| MySQL HeatWave | **1 個**（§3） |
| Autonomous Database | 2 個。各 1 OCPU・20 GB・同時 30 セッション（§4） |
| Load Balancer | Flexible 1 個（10 Mbps）。Network Load Balancer 1 個 |
| VCN | 2 個まで（Free Tier のテナンシ） |
| 外向きの転送 | 10 TB/月 |
| Monitoring | 取り込み 5 億点/月・読み出し 10 億点/月 |
| Notifications | メール 1,000 通/月 |
| Logging | ログの保存 10 GB/月（価格の API。下の注） |
| Email Delivery | 3,000 通/月 |
| Resource Manager | スタック 100 個・同時ジョブ 2 個 |

- Compute と DB は **ホームリージョン** にしか無料で作れない。
- A1 は、リージョンによっては空きが無く "Out of host capacity" で作れないことが多い。可用性ドメインが1つのリージョンでは、他のドメインに逃げることもできない。
- 確かめられなかったもの:
  - **OCIR**（コンテナ・レジストリ）: 「レジストリ自体は無料、保存は Object Storage の料金」とされるが、無料枠に含まれるかは公式に確かめられなかった。
  - **Artifact Registry**: 料金と無料枠を確かめていない。
- **OCI DevOps は Always Free ではない**。パイプラインそのものは無料で、ビルドの実行の分だけ課金される。
- **DNS**（公開のゾーン）: Always Free のリソースの一覧に無い。価格の API では、問い合わせ 100 万回あたり 131.75 円（0.85 USD。品目 B88525）で、無料の回数は無い。ゾーンそのものの品目は無い（2026-11-23）。テナンシの上限（`oci limits value list --service-name dns`）は、ゾーン 1,000・レコード 25,000 だった（2026-11-23 実測。テナンシによって違いうる）。
- **予約済みの公開 IP**: Oracle の価格の API（§6）に品目が無い。予約済みの公開 IP を出したときの Oracle の発表では「料金はかからない」とされている（古い発表で、今の価格表の記述では確かめられなかった）。上限（`reserved-public-ip-count`）はリージョンあたり 50 だった（2026-11-13 実測。テナンシによって違いうる）。
- **Network Load Balancer**: 公式文書の概要に「Network load balancers are Always Free tier.」とある。帯域の設定は無く、通信に合わせて広がる（「Capable of scaling beyond 8 Gbps.」）。価格の API に品目が無い。テナンシの上限（`max-nlb-flexible-count`）はリージョンあたり 10 だった（2026-11-25 実測。テナンシによって違いうる）。
- **NAT ゲートウェイ・サービス・ゲートウェイ**: 価格の API に品目が無い。料金のページは読めず、無料かは公式の料金の記述で確かめていない（2026-11-25）。NAT ゲートウェイの上限（`nat-gateway-count`）は 1 だった（2026-11-25 実測）。
- **Logging**: 価格の API では、品目は「OCI - Logging - Storage」（B92593）の 1 つだけで、**月 10 GB まで 0 円**、超えた分は 1 GB・月あたり 0.05 USD（7.75 円）。PAYG の品目そのものに 10 GB までの無料の段が付いている。1 回の送信ごとに付帯の情報（最低 500 バイト）が加わり、量に数えられる。取り込みと検索に料金がかかるかは、docs.oracle.com で確かめられなかった（未確認。価格の API に品目は無い）。保存の日数は 30 日刻みで最大 180 日（2026-11-26）。
- **Logging Analytics**: 価格の API で、1 単位で月 372 USD から（2026-11-26）。
- **Cloud Guard**: 設定と操作の見張り（Configuration・Activity の検出）は、価格の API に品目が無い。無料のテナンシ（Always Free だけ）では有効にできない（公式文書）。VM の中を見張る Instance Security は、Standard が 1 台・1 時間あたり 0 円、Enterprise が 1 台・1 時間あたり 1.0695 円（1 台を 1 か月動かすと約 780 円）。都度の問い合わせ（Enterprise）は月 95 万回まで 0 円、それを超えると 1 回 0.155 円（2026-11-13 に価格の API で確認。品目 B108188・B108189・B108190）。無料のレシピ（Standard）は、検出の規則が 2 つで、1 リージョンあたり 5 台まで（公式文書）。

## 3. MySQL HeatWave の Always Free

| 項目 | 値 |
|---|---|
| 個数 | テナンシに 1 個（無料・有料のどちらのテナンシでも）。ホームリージョンだけ |
| シェイプ | `MySQL.Free`（1 ECPU・8 GB・1 Gbps）。構成は単体（`MySQL.Free.Standalone`） |
| ストレージ | 50 GB で固定 |
| HeatWave のクラスタ | `HeatWave.Free`（1 ノード・16 GB）を付けられる。分析用 |
| 版 | 作るときに最新。**保守のたびに最新へ上がる** |
| バックアップ | 自動だけ。**保持 1 日** で変えられない。手動バックアップと過去の時点への復元（PITR）はできない |
| 高可用性・リードレプリカ | 無し |
| ネットワーク | VCN のプライベート・サブネットに置く |
| 作成の失敗 | 空きが無いと `OutOfHostCapacity` になることがある |
| サポート | SLA なし。Oracle のサポートの対象外 |

有料の種類に変えるとき（2026-11-26 に調べた）:

- `MySQL.Free` から有料の種類へは、その場で変えられる。変えると課金される DB System になり、DB は再起動する（公式文書 [Editing a DB System](https://docs.oracle.com/en-us/iaas/mysql-database/doc/editing-db-system.html)）。
- いちばん小さい有料の種類は `MySQL.2`（2 ECPU・16 GiB）。価格の API の単価は、ECPU 1 時間 0.0366 USD（5.673 円。B108030）、ストレージ 1 GB・月 0.04 USD（6.2 円。B92426）、バックアップの保存 1 GB・月 0.04 USD（6.2 円。B92483）。2 ECPU を常に動かし、ストレージ 50 GB なら、月に約 56.5 USD（約 8,750 円）の見込み（2 ECPU 分が課金されることと、地域で単価が同じことは推測）。
- バックアップの保存は、動いている DB System のストレージと同じ量までは無料（公式文書）。

公式文書に見つからなかったこと:

- 使わないと止まる・消されるといった条件（Autonomous Database の「7 日で停止」に当たるもの）
- 削除防止を有効にできるか

実際に作って確かめたこと（2026-11-09、版 `26.10.0-u1-cloud`）:

- 作るときにバックアップの方針（`backupPolicy`）を指定すると、`400 InvalidParameter`（Always Free の DB には指定できない）になる。
- 作成にかかった時間は約 17 分。
- `max_connections` は 200。`time_zone` は UTC。`partial_revokes` は有効。
- パスワードの検査（`validate_password`）が MEDIUM で効いている。8 文字以上で、英大文字・英小文字・数字・記号を各 1 つ以上含む必要がある。
- DB を作る API は、管理者のパスワードに特殊文字を 1 つ以上求める。`~` は特殊文字として数えない（`~` を含んでもよいが、ほかの記号が 1 つ要る）。`!@#$%&*()-_=+[]{}<>:?.` はどれも 1 つで数えられた（2026-11-22 実測）。記号が足りないと `400 InvalidParameter`（「adminPassword … may not be valid」）になる。文書は「特殊文字（英数字でないもの）」とだけ書いている（[Changing the Administrator Password of a DB System](https://docs.oracle.com/en-us/iaas/mysql-database/doc/changing-administrator-password-db-system.html)）。

## 4. Autonomous Database の Always Free

| 項目 | 値 |
|---|---|
| 止まる条件 | **7 日使わないと自動で停止**（接続と CPU の使用で測る。SQL を実行する接続が成功すれば測り直し）。止まったまま累計 90 日で削除されうる |
| バックアップ | 手動バックアップ・過去の時点への復元はできない |
| ネットワーク | プライベート・エンドポイントは使えない（公開の口をアクセス制御の一覧で絞る） |
| 手元で動かす | 専用のコンテナ（推奨 4 CPU・8 GB）。一部の機能が無い |
| サポート | SLA なし |

## 5. アイドル回収

Always Free の Compute は、7 日間で次の **すべて** を満たすと回収されうる。

- CPU 使用率（95 パーセンタイル）が 20% 未満
- ネットワーク使用率が 20% 未満
- メモリ使用率が 20% 未満（A1 だけ）

PAYG のアカウントは対象外という情報が多いが（コミュニティの投稿・ブログ）、公式文書では確かめられなかった。公式文書は「Always Free の Compute のインスタンス」が対象と書くだけで、PAYG のアカウントの扱いには触れていない（2026-11-13 に確認し直した）。

## 6. 出典

- [Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)（Compute・ストレージ・DB・ネットワーク・アイドル回収）
- [MySQL HeatWave Service の機能（Always Free）](https://docs.oracle.com/iaas/mysql-database/doc/features-mysql-heatwave-service.html)
- [Always Free の MySQL の DB システムの作成](https://docs.oracle.com/iaas/mysql-database/doc/creating-always-free-db-system.html)
- [Changing the Administrator Password of a DB System](https://docs.oracle.com/en-us/iaas/mysql-database/doc/changing-administrator-password-db-system.html)（管理者のパスワードの決まり）
- [Always Free Autonomous Database の制限](https://docs.oracle.com/en-us/iaas/autonomous-database-serverless/doc/autonomous-always-free.html)
- Oracle の価格の API: `https://apexapps.oracle.com/pls/apex/cetools/api/v1/products/?currencyCode=JPY`（Oracle の見積もりの道具が使う価格表。Cloud Guard・公開 IP は 2026-11-13、DNS は 2026-11-23、ロードバランサーとゲートウェイは 2026-11-25）
- [Release Announcement: Reserved Public IPs](https://blogs.oracle.com/cloud-infrastructure/release-announcement-reserved-public-ips-are-now-available-on-oracle-cloud-infrastructure)（予約済みの公開 IP は無料とする発表）
- [Network Load Balancer Overview](https://docs.oracle.com/en-us/iaas/Content/NetworkLoadBalancer/overview.htm)（Always Free・帯域）
- [Instance Security](https://docs.oracle.com/en-us/iaas/cloud-guard/using/cgis.htm)（Cloud Guard の Instance Security の無料のレシピ）
- [Getting Started with Cloud Guard](https://docs.oracle.com/en-us/iaas/cloud-guard/using/part-start.htm)（無料のテナンシでは有効にできない）
