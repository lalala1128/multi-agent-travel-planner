"""将同一份任务快照渲染成可打印的中文行程单。"""

from datetime import timedelta
from html import escape

from schemas import TaskRecord


def table(headings, rows):
    header = "".join(f"<th scope='col'>{escape(h)}</th>" for h in headings)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(value))}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return f"<div class='scroll'><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>"


def plan_sections(plan):
    budget = plan.budget_result
    if budget:
        if budget.within_budget is None:
            reason = "没有可用房源" if budget.reason == "no_hotel_offer" else "缺少可用汇率"
            yield f"<h2>预算待核算</h2><p>{reason}。</p>"
        else:
            label = "剩余" if budget.within_budget else "超出"
            yield (f"<h2>预计总费用 ¥{budget.total_cost:,.2f}</h2>"
                   f"<p>预算 ¥{plan.preferences.budget:,.2f} · {label} ¥{abs(budget.remaining):,.2f}</p>")
        if budget.rounds:
            yield table(["方案", "机票（元）", "住宿（元）", "当地开销（元）", "合计（元）"], [
                ({"standard": "标准活动", "economy": "经济活动", "free": "免费活动", "fixed": "固定每日开销"}.get(r.activity_plan, r.activity_plan),
                 f"{r.flight_cny:,.2f}", f"{r.hotel_cny:,.2f}", f"{r.activity_cny:,.2f}", f"{r.total_cny:,.2f}")
                for r in budget.rounds
            ])
        if budget.hotel_budget_limit_cny is not None:
            yield f"<p>保留最终航班和活动时，整段住宿最多可花 ¥{budget.hotel_budget_limit_cny:,.2f}。</p>"
    if plan.flight and plan.activity:
        labels = {"demo": "演示估算", "user_input": "本人填写"}
        yield (f"<p>机票来源：{escape(labels.get(plan.flight.provider, plan.flight.provider))} · "
               f"当地开销来源：{escape(labels.get(plan.activity.provider, plan.activity.provider))}</p>")
    hotel = plan.hotel
    if hotel:
        yield f"<h2>{escape(hotel.hotel_name or '住宿方案')}</h2>"
        yield (f"<p>{hotel.nights} 晚合计 {escape(hotel.currency)} {hotel.total_cost:,.2f}"
               f" · {escape({'user_input':'本人填写','demo':'演示估算'}.get(hotel.provider, hotel.provider))}"
               f" · 记录时间 {escape(hotel.quoted_at.isoformat(timespec='minutes'))}</p>")
        if plan.preferences.hotel_check_in:
            start = plan.preferences.hotel_check_in
            yield f"<p>入住 {start} · 退房 {start + timedelta(days=hotel.nights)}</p>"
        if budget and budget.hotel_conversion:
            fx = budget.hotel_conversion
            yield (f"<p>按 {fx.rate_date} 欧洲央行参考汇率，1 {escape(fx.source_currency)}"
                   f" 折合 {fx.cny_per_unit:.4f} 元，住宿约 ¥{fx.amount_cny:,.2f}。</p>")
        if hotel.shortlist:
            yield table(["候选酒店", "住宿原价", "折合人民币"], [
                (h.hotel_name, f"{h.currency} {h.total_price:,.2f}", f"¥{h.total_cny:,.2f}")
                for h in hotel.shortlist
            ])
    if plan.knowledge_answer:
        answer = plan.knowledge_answer
        yield f"<h2>{escape(plan.preferences.knowledge_question)}</h2><p>{escape(answer.answer)}</p>"
        for chunk in plan.knowledge:
            if chunk.id in answer.citations:
                yield (f"<details><summary>{escape(chunk.source)} · 片段 {chunk.chunk_index + 1}</summary>"
                       f"<p>{escape(chunk.text)}</p></details>")


def render_report(record: TaskRecord) -> str:
    refresh = ""
    title = "旅行规划"
    if record.status in {"queued", "running"}:
        refresh = '<meta http-equiv="refresh" content="5">'
        state = "正在排队" if record.status == "queued" else "正在规划"
        body = f"<p>{state}，页面将在 5 秒后更新。</p>"
    elif record.status == "failed":
        body = f"<p>规划失败。失败阶段：{escape(record.error_stage or '未知')}。</p>"
    elif record.result:
        plan = record.result
        city = plan.destination.city if plan.destination else "目的地"
        title = f"{city} · {plan.preferences.days} 日行程单"
        body = f"<p>从 {escape(plan.preferences.departure_city)} 出发</p>" + "".join(plan_sections(plan))
    else:
        body = "<p>暂无规划结果。</p>"
    library = ' · <a href="/my/trips">我的行程</a>' if record.owner else ''
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">{refresh}<title>{escape(title)}</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f4f6f1;color:#173631;font:16px/1.7 Inter,"Microsoft YaHei",sans-serif}}
main{{max-width:54rem;margin:3vw auto;background:white;padding:clamp(1.2rem,5vw,3.5rem);border-top:5px solid #23645b}}
h1,h2{{line-height:1.3}}h2{{margin:2rem 0 .5rem}}p{{overflow-wrap:anywhere}}.scroll{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}}td,th{{padding:.5rem .7rem;text-align:left;border-bottom:1px solid #dce5e0}}
th{{background:#edf4f0}}summary{{cursor:pointer}}a{{color:#176258}}footer{{margin-top:2rem}}
@media print{{main{{margin:0;max-width:none;padding:0;border:0}}footer{{display:none}}tr{{break-inside:avoid}}}}
</style></head><body><main><h1>{escape(title)}</h1>{body}
<footer><a href="/">新建旅行预算</a>{library} · <a href="/tasks/{escape(record.id, quote=True)}">查看原始任务数据</a></footer></main></body></html>"""
