# OCI Network Load Balancer

OCI のネットワーク・ロードバランサー（NLB）。L4（TCP・UDP）で通信を受け、そのまま後ろのサーバ（バックエンド）へ渡す。TLS を解かない。

- **確かめた日**: 2026-11-25（Oracle の公式文書、Terraform の OCI プロバイダの文書、このテナンシの上限の読み取り）

## 1. 要点

| 項目 | 内容 |
|---|---|
| 働き | 「a pass-through (non-proxy solution)」。L3・L4 の情報だけで振り分ける。TLS の終端はしない |
| 料金 | 「Network load balancers are Always Free tier.」。料金と上限の値は [oci-free-tier.md](oci-free-tier.md) |
| 帯域 | 帯域の設定は無く、通信に合わせて広がる |
| 公開 IP | 公開の NLB は、パブリック・サブネットに置く。IP は OCI が割り当てるもの（エフェメラル）か、予約済みのものを使える |
| ヘルスチェック | TCP・HTTP・HTTPS・UDP・DNS。ヘルスチェックの送信元は「a compute instance managed by the Network Load Balancer service」で、IP の範囲は書かれていない |
| セキュリティ | NLB に NSG を付けられる。リスナーを作ったら、VCN のセキュリティの規則でリスナーへの通信を許す必要がある |

## 2. 組み立て

- リスナー（受ける番号とプロトコル）・バックエンド・セット（振り分けの方針とヘルスチェック）・バックエンド（後ろのサーバとその番号）からなる。
- 1 つのバックエンド・セットは、1 つのリスナーにだけ結び付く。
- リスナーは番号ごとに作れる（例: TCP 80 と TCP 443 を別々に）。「どの番号でも」のリスナーもある。
- Terraform の OCI プロバイダ（9.12.1）では、NLB・バックエンド・セット・バックエンド・リスナーが別々の資源。バックエンドは `target_id` にインスタンスの OCID を書ける。

## 3. 送信元 IP の保持

- バックエンド・セットの `is_preserve_source`。有効にすると、バックエンドには利用者の IP のまま届く（「Backend servers see the original source IP.」）。**既定で有効**。
- 有効のときは、IP アドレスで指定したバックエンドを足せない（インスタンスの OCID で指定する）。
- 有効のときは、PROXY プロトコル（v2）を併せて使えない。
- 有効のとき、バックエンドのセキュリティの規則に何を許すべきか、バックエンドの返事がどう利用者に返るかは、公式文書に書かれていない（未確認）。

## 4. 出典

- [Network Load Balancer Overview](https://docs.oracle.com/en-us/iaas/Content/NetworkLoadBalancer/overview.htm)（働き・料金・帯域）
- [Creating a Network Load Balancer](https://docs.oracle.com/en-us/iaas/Content/NetworkLoadBalancer/NetworkLoadBalancers/create-network-load-balancer.htm)（公開 IP・NSG・リスナーとセキュリティの規則）
- [Preserving the Source IP](https://docs.oracle.com/en-us/iaas/Content/NetworkLoadBalancer/BackendSets/preserve-backend-set-source-id.htm)（送信元 IP の保持）
- [Health Check Policies](https://docs.oracle.com/en-us/iaas/Content/NetworkLoadBalancer/HealthCheckPolicies/health-check-policy-management.htm)（ヘルスチェック）
- [Backend Sets](https://docs.oracle.com/en-us/iaas/Content/NetworkLoadBalancer/BackendSets/backend-set-management.htm)（バックエンド・セットとリスナー）
- [oci_network_load_balancer_backend](https://github.com/oracle/terraform-provider-oci/blob/master/website/docs/r/network_load_balancer_backend.html.markdown)（`target_id`）
