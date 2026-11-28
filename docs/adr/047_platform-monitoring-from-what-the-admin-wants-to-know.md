# 047 基盤の監視は、管理者が知りたい 4 つをアラームで見る

- 決めた日: 2026-11-28

## 背景

ADR 007 は、「VM が 1 時間ごとに HeatWave に問い合わせ、失敗したときと、届かなくなったときにメールする」と決めた。実装はされていなかった。ADR 007 は MDD を始める前のもので、人の目がほとんど入っていない。

そのため、基盤の管理者が何を知りたいかから考え直した。

| 知りたいこと | なぜ |
|---|---|
| 利用者が外からアプリに届くか（VM が止まった、Caddy が落ちた） | 全プロジェクトが外から見えなくなる |
| DB が動いているか | 全プロジェクトが共有している |
| VM のメモリとディスクが足りなくなっていないか | 1 つの VM に全プロジェクトが乗る |

この ADR は、ADR 007 を置き換える。週 1 回のダンプのアラーム（`alarm-afp-backup`）は変えない。

## 決定

アラームを 4 つ足す。送り先は、どれも今のトピック（`topic-afp-devops`）。

| アラーム | 見るもの | 鳴るとき |
|---|---|---|
| `alarm-afp-nlb-unhealthy` | NLB が 80・443 番にしている TCP のヘルスチェックの結果（`oci_nlb` の `UnhealthyBackendsPerNlb`） | 5 分続けて 0 より大きい |
| `alarm-afp-check-db` | `afp check-db` が 1 時間ごとに送る `afp/check_db_ok`（DB が `SELECT 1` に答えたら 1、答えなければ 0） | 直近 1 時間に 0 がある |
| `alarm-afp-vm-memory` | Oracle Cloud Agent の監視のプラグインが送る `MemoryUtilization`（`oci_computeagent`） | 5 分の平均が 90% を超え、それが 5 分続く |
| `alarm-afp-vm-disk` | `afp check-disk` が 1 時間ごとに送る `afp/disk_used_percent`（`/` の使用率。`df` と同じ数え方） | 直近 1 時間に 90% を超えた値がある |

- `afp check-db` と `afp check-disk` は、VM の systemd の timer で 1 時間ごとに動く（`afp install` が置く）。ロックは取らない。デプロイを待たないため。
- この 2 つのログは、失敗したときだけバケットに置く。うまくいったときは残さない。1 時間ごとのログがたまらないため。
- VM の監視のプラグイン（`Compute Instance Monitoring`）を、VM の設定で明示的に有効にする。
- アプリが正しく動いているか（502 を返す、など）は、今までどおり各プロジェクトが見る。

## 理由

- NLB のメトリクスは、有効にする操作が要らず、VM の側を変えずに使える（[NLB のメトリクス](https://docs.oracle.com/en-us/iaas/Content/NetworkLoadBalancer/Metrics/metrics.htm)）。本番で、1 分ごとにデータがあることを確かめた（2026-11-28）。
- 1 時間に 1 点だけ送るメトリクスは、`[1h]` の間隔で読む。文書は、メトリクスを送る間隔以上の間隔にするよう勧めている（[Alarms のベストプラクティス](https://docs.oracle.com/en-us/iaas/Content/Monitoring/Concepts/alarmsbestpractices.htm)）。`[1h]` はアラームで使える（[MQL](https://docs.oracle.com/en-us/iaas/Content/Monitoring/Reference/mql.htm)）。
- DB を見るのに、HeatWave そのもののメトリクスを使わず、VM から問い合わせる。実際につながるかを見るので確かである。また、文書に「保守の間は、メトリクスを見ない」とあり、HeatWave のメトリクスでは、保守のたびに誤って鳴るおそれがある（[HeatWave のメトリクス](https://docs.oracle.com/en-us/iaas/mysql-database/doc/metrics.html)）。
- ディスクの空きのメトリクスは、監視のプラグインに無い（読み書きの量だけ。[Compute のメトリクス](https://docs.oracle.com/en-us/iaas/Content/Compute/References/computemetrics.htm)）。`afp check-db` と同じ作り（timer、メトリクスを送る部分、権限）に乗せれば小さく済む。
- 監視のプラグインは、VM の設定に書かなくても `MemoryUtilization` を送っていた（2026-11-28）。しかし、既定で有効かは文書に書いていない。そのため、明示的に有効にする。
- 結果が届かないことのアラーム（`absent()`）は作らない。VM が止まったことは `alarm-afp-nlb-unhealthy` でわかる。timer だけが止まったときは気付けないが、そのためにアラームを増やさない。

## 採らなかった案

| 案 | 理由 |
|---|---|
| OCI の Health Checks のサービスで、外から URL を見る | 無料の範囲が無い（1 つの URL で月 0.30 USD）。NLB のメトリクスで、ほぼ同じことがわかる |
| HeatWave のメトリクスで DB を見る | 上の理由のとおり |
| DB のストレージの使用率（`DbVolumeUtilization`）を見る | 会議で、今回は入れないと決めた |
| `afp check-db` にディスクの使用率を足す | 名前と中身が合わなくなる |
| 1 時間ごとのメトリクスを `[1m]` で読む | データ点のある 1 分しか条件が成り立たず、次の点を待たずに RESET で戻る（文書の決まりに当てはめた推測） |

## 影響

- アラームが 4 つ増える（合わせて 5 つ。リージョンの上限は 50）。メトリクスの点とメールは、無料の範囲に収まる（[Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)）。
- NLB のヘルスチェックは TCP なので、Caddy が動いていてアプリが 502 を返すときは分からない。それは各プロジェクトが見る。
- 証明書が切れたことは、この監視では分からない。
