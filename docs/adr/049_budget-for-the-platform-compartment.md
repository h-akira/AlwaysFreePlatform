# 049 base のスタックが、基盤のコンパートメントの予算とアラートを作る

- 決めた日: 2026-11-29

## 背景

これまで、基盤は予算（OCI の Budgets）を作らないとしていた。費用は、基盤の管理者が OCI のコンソールで、テナンシ全体の予算とアラートを手で作って見るものとしていた。

基盤のほとんどは無料枠に収まるが、無料枠の外の少額のリソースも使う（自動のデプロイのビルド・DNS の問い合わせ・OCIR の保存など）。また、作り方を誤ったときや、無料枠が変わったときには、思わない費用がかかりうる。

テナンシ全体の予算は、テナンシのすべての費用を合わせて見る。基盤のほかにリソースがあるテナンシでは、そのうちの基盤の分が分からない。基盤の分だけが増えても、全体の予算に達するまで気付けない。

この ADR は、「基盤は予算を作らない」とした扱いを置き換える。ADR 034 の、base に置くものの基準に 1 つ足す（ADR 034 のほかの決定は変えない）。

## 決定

- 変数 `budget_amount`（月の予算の額。テナンシの通貨で、整数）を、base のスタックに足す。既定は null。
- `budget_amount` を設定したときだけ、base のスタックが次の 2 つを作る。設定しなければ、何も作らない。
  - 予算 `budget-afp-main`: 基盤のコンパートメント（`compartment-afp-main`。その下のコンパートメントを含む）の費用を、月ごとに見る。予算は、何を見るものでもテナンシのルートに作る（OCI の決まり）。
  - アラートのルール `alertrule-afp-main`: その月の実際の費用（予測でなく）が予算の 100% に達したら、`notification_email` にメールする。
- base のスタックも `notification_email` を受け取る（本体と同じ値）。
- テナンシ全体の予算は、今までどおり、基盤の管理者がコンソールで作ってよい。基盤は作らない。

## 理由

- 思わない費用に早く気付くため。基盤のコンパートメントだけを見る予算なら、テナンシのほかの費用に埋もれず、基盤の分が増えたことが分かる。
- 予算は、基盤のコンパートメントを名前でなく OCID で指す。コンパートメントを作るのは base なので、同じスタックに置けば値を受け渡さずに済む（本体は base のリソースを名前で探すだけで、値を受け渡す仕組みを作らない）。
- 本体を destroy して作り直す間も、予算は見続けてほしい。本体の destroy で消えないもの（Terraform の外で作る OCIR のリポジトリとその保存の費用など）は、本体が無い間もコンパートメントに残る。
- 額は環境ごとの値なので、公開のリポジトリに書かず、非公開の設定（`terraform.tfvars.json`）で渡す。設定しない人には何も作らない。
- アラートを 1 つ（実際の費用が 100%）にとどめる。予測の費用のアラートや、途中の割合のアラートを足すと、少額の基盤では誤って鳴りやすく、ルールも増える。
- 料金: 予算とアラートのルールに料金がかかるという記述は、見つからなかった（2026-11-29）。
  - Oracle の価格の API（`https://apexapps.oracle.com/pls/apex/cetools/api/v1/products/?currencyCode=JPY`。668 品目）に、Budgets の品目は無い。
  - 予算の説明（[Budgets](https://docs.oracle.com/en-us/iaas/Content/Billing/Concepts/budgetsoverview.htm)・[Creating a Budget](https://docs.oracle.com/en-us/iaas/Content/Billing/Tasks/create-budget.htm)）には、料金と、無料のテナンシで使えないことの記述が無い。
  - 無料と明記した公式の記述も見つけられなかった（未確認）。上は「品目が無い」ことから無料と判断したもの。
- Terraform の引数は、プロバイダのドキュメントで確かめた（[oci_budget_budget](https://docs.oracle.com/en-us/iaas/tools/terraform-provider-oci/latest/docs/r/budget_budget.html)・[oci_budget_alert_rule](https://docs.oracle.com/en-us/iaas/tools/terraform-provider-oci/latest/docs/r/budget_alert_rule.html)。2026-11-29）。`target_compartment_id` は非推奨で、`target_type = "COMPARTMENT"` と `targets` を使う。値の候補（`COMPARTMENT`・`MONTHLY`・`ACTUAL`・`PERCENTAGE`）は、OCI の Python SDK（OCI CLI 3.96.0 に同梱）の定数でも確かめた。

## 採らなかった案

| 案 | 理由 |
|---|---|
| 今までどおり、基盤は予算を作らない | テナンシ全体の予算では、基盤の分が分からない |
| 本体のスタックに置く | 本体を destroy している間は、見る予算が無くなる。コンパートメントの OCID も base から受け渡すことになる |
| 額を決めて、いつも作る | 額は使う人ごとに違う。公開のリポジトリに額を書くことになる |
| 予算に達したら、リソースを止める | 予算は知らせるだけで、止める仕組みは無い。止める仕組みを足すと、基盤が複雑になる |
| 予測の費用のアラートや、50%・80% のアラートも作る | 少額の基盤では誤って鳴りやすい。要るなら、管理者がコンソールで足せる |
| アラートを `topic-afp-devops` に送る | トピックは本体のスタックにあり、base から使えない。予算のアラートは、宛先のメールのアドレスを直接持てる |

## 影響

- base のスタックが、`notification_email` を必ず受け取る。`budget_amount` は、設定したときだけ渡す（`scripts/stack.sh` が渡す変数を絞っている）。
- 1 つのコンパートメントに作れる予算は 1 つだけ（[Creating a Budget](https://docs.oracle.com/en-us/iaas/Content/Billing/Tasks/create-budget.htm)）。基盤のコンパートメントに手で予算を作っていたら、先に消す。
- 予算はテナンシのルートに作るので、base を apply する人に、ルートで予算を扱う権限が要る。
- `notification_email` を変えたら、本体だけでなく base も plan・apply し直す。
