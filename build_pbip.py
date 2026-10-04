"""Generate the Power BI project (PBIP): star-schema data, TMDL semantic model, DAX measures and report pages.

Run:  python build_pbip.py     then open OlistSales.pbip in Power BI Desktop and click Refresh.
"""
import json
import uuid
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SRC = ROOT.parent / "olist-ecommerce-analytics" / "data" / "processed" / "tableau_orders_slim.csv"
NAME = "OlistSales"
MODEL = ROOT / f"{NAME}.SemanticModel"
REPORT = ROOT / f"{NAME}.Report"

REGIONS = {
    "North": ["Acre", "Amapa", "Amazonas", "Para", "Rondonia", "Roraima", "Tocantins"],
    "Northeast": ["Alagoas", "Bahia", "Ceara", "Maranhao", "Paraiba", "Pernambuco", "Piaui",
                  "Rio Grande do Norte", "Sergipe"],
    "Central-West": ["Distrito Federal", "Goias", "Mato Grosso", "Mato Grosso do Sul"],
    "Southeast": ["Espirito Santo", "Minas Gerais", "Rio de Janeiro", "Sao Paulo"],
    "South": ["Parana", "Rio Grande do Sul", "Santa Catarina"],
}

# name -> (DAX, format string)
MEASURES = {
    "Total Revenue": ("SUM(Orders[order_value])", "#,0"),
    "Total Orders": ("COUNTROWS(Orders)", "#,0"),
    "Avg Order Value": ("DIVIDE([Total Revenue], [Total Orders])", "#,0.00"),
    "Avg Review Score": ("AVERAGE(Orders[review_score])", "0.00"),
    "Avg Delivery Days": ("AVERAGE(Orders[delivery_days])", "0.0"),
    "Late Orders": ('CALCULATE([Total Orders], Orders[delivery_status] = "Late")', "#,0"),
    "Late Delivery %": ("DIVIDE([Late Orders], [Total Orders])", "0.0%"),
    "Repeat Customer Orders %": ('DIVIDE(CALCULATE([Total Orders], Orders[customer_type] = "Repeat"), [Total Orders])', "0.0%"),
    "Revenue Previous Month": ("CALCULATE([Total Revenue], DATEADD('Date'[Date], -1, MONTH))", "#,0"),
    "MoM Growth %": ("DIVIDE([Total Revenue] - [Revenue Previous Month], [Revenue Previous Month])", "0.0%"),
    "Revenue YTD": ("TOTALYTD([Total Revenue], 'Date'[Date])", "#,0"),
    "Revenue Share %": ("DIVIDE([Total Revenue], CALCULATE([Total Revenue], ALLSELECTED(Orders)))", "0.0%"),
    "Category Rank": ("RANKX(ALL(Orders[category]), [Total Revenue], , DESC, Dense)", "0"),
    "Bad Review %": ("DIVIDE(CALCULATE([Total Orders], Orders[review_score] <= 2), CALCULATE([Total Orders], NOT ISBLANK(Orders[review_score])))", "0.0%"),
}

# table -> [(column, TMDL data type, M type, summarizeBy)]
COLUMNS = {
    "Orders": [
        ("order_date", "dateTime", "type date", "none"), ("state", "string", "type text", "none"),
        ("category", "string", "type text", "none"), ("order_value", "double", "type number", "sum"),
        ("payment_type", "string", "type text", "none"), ("delivery_days", "int64", "Int64.Type", "none"),
        ("delivery_status", "string", "type text", "none"), ("review_score", "double", "type number", "none"),
        ("customer_type", "string", "type text", "none"), ("late_flag", "int64", "Int64.Type", "none"),
    ],
    "Date": [
        ("Date", "dateTime", "type date", "none"), ("Year", "int64", "Int64.Type", "none"),
        ("Quarter", "string", "type text", "none"), ("Month Number", "int64", "Int64.Type", "none"),
        ("Month Name", "string", "type text", "none"), ("Month Start", "dateTime", "type date", "none"),
        ("Weekday", "string", "type text", "none"),
    ],
    "State": [("state_name", "string", "type text", "none"), ("region", "string", "type text", "none")],
}
FILES = {"Orders": "fact_orders.csv", "Date": "dim_date.csv", "State": "dim_state.csv"}


def q(name):
    return f"'{name}'" if " " in name or "%" in name else name


def build_data():
    DATA.mkdir(parents=True, exist_ok=True)
    orders = pd.read_csv(SRC)
    orders.to_csv(DATA / FILES["Orders"], index=False)
    days = pd.date_range("2017-01-01", "2018-12-31", freq="D")
    pd.DataFrame({
        "Date": days.date, "Year": days.year, "Quarter": "Q" + days.quarter.astype(str),
        "Month Number": days.month, "Month Name": days.strftime("%b"),
        "Month Start": days.to_period("M").start_time.date, "Weekday": days.day_name(),
    }).to_csv(DATA / FILES["Date"], index=False)
    pd.DataFrame([(s, r) for r, states in REGIONS.items() for s in states],
                 columns=["state_name", "region"]).to_csv(DATA / FILES["State"], index=False)
    return len(orders)


def m_query(table):
    path = str(DATA / FILES[table])
    types = ", ".join(f'{{"{c}", {m}}}' for c, _, m, _ in COLUMNS[table])
    steps = [
        f'Source = Csv.Document(File.Contents("{path}"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv])',
        "Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true])",
    ]
    last = "Promoted"
    if table == "Orders":
        steps.append('RemovedCountry = Table.RemoveColumns(Promoted, {"country"})')
        last = "RemovedCountry"
    steps.append(f'Typed = Table.TransformColumnTypes({last}, {{{types}}}, "en-US")')
    last = "Typed"
    if table == "Orders":
        steps.append("Cleaned = Table.SelectRows(Typed, each [order_value] <> null and [order_value] > 0)")
        steps.append('AddedBucket = Table.AddColumn(Cleaned, "delivery_bucket", each if [delivery_days] <= 7 then "1. 0-7 days" '
                     'else if [delivery_days] <= 14 then "2. 8-14 days" else if [delivery_days] <= 21 then "3. 15-21 days" '
                     'else "4. 22+ days", type text)')
        last = "AddedBucket"
    body = ",\n".join(f"\t\t\t\t    {s}" for s in steps)
    return f"\t\t\t\tlet\n{body}\n\t\t\t\tin\n\t\t\t\t    {last}"


def table_tmdl(table):
    out = [f"table {q(table)}"]
    if table == "Date":
        out.append("\tdataCategory: Time")
    out.append("")
    if table == "Orders":
        for name, (dax, fmt) in MEASURES.items():
            out += [f"\tmeasure {q(name)} = {dax}", f"\t\tformatString: {fmt}", ""]
    cols = list(COLUMNS[table]) + ([("delivery_bucket", "string", "", "none")] if table == "Orders" else [])
    for name, dtype, _, summarize in cols:
        out.append(f"\tcolumn {q(name)}")
        out.append(f"\t\tdataType: {dtype}")
        if dtype == "dateTime":
            out.append("\t\tformatString: Short Date")
        if table == "Date" and name == "Date":
            out.append("\t\tisKey")
        out += [f"\t\tsummarizeBy: {summarize}", f"\t\tsourceColumn: {name}", ""]
    out += [f"\tpartition {q(table)} = m", "\t\tmode: import", "\t\tsource =", m_query(table), ""]
    return "\n".join(out)


def build_model():
    d = MODEL / "definition"
    (d / "tables").mkdir(parents=True, exist_ok=True)
    (MODEL / "definition.pbism").write_text(json.dumps({"version": "4.0", "settings": {}}, indent=2))
    (d / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1567\n")
    refs = "\n".join(f"ref table {q(t)}" for t in COLUMNS)
    (d / "model.tmdl").write_text(
        "model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n"
        f"\tsourceQueryCulture: en-US\n\n{refs}\n")
    (d / "relationships.tmdl").write_text(
        "relationship orders_date\n\tfromColumn: Orders.order_date\n\ttoColumn: Date.Date\n\n"
        "relationship orders_state\n\tfromColumn: Orders.state\n\ttoColumn: State.state_name\n")
    for table in COLUMNS:
        (d / "tables" / f"{table}.tmdl").write_text(table_tmdl(table), encoding="utf-8")


# ---------- report (legacy report.json) ----------
ALIAS = {"Orders": "o", "Date": "d", "State": "s"}


def field(table, name, measure=False):
    kind = "Measure" if measure else "Column"
    return {kind: {"Expression": {"SourceRef": {"Source": ALIAS[table]}}, "Property": name}}


NAVY, GREY, BORDER, PAGE_BG = "#1F4E79", "#6B7280", "#E1E5EA", "#F3F4F6"


def lit(value):
    return {"expr": {"Literal": {"Value": value}}}


def color(hex_code):
    return {"solid": {"color": lit(f"'{hex_code}'")}}


def frame(title=None, fill="#FFFFFF"):
    """Shared look for every visual: white card, soft border, shadow, bold title."""
    vc = {"background": [{"properties": {"show": lit("true"), "color": color(fill), "transparency": lit("0D")}}],
          "border": [{"properties": {"show": lit("true"), "color": color(BORDER), "radius": lit("8D")}}],
          "dropShadow": [{"properties": {"show": lit("true")}}]}
    if title:
        vc["title"] = [{"properties": {"show": lit("true"), "text": lit(f"'{title}'"), "fontSize": lit("12D"),
                                       "bold": lit("true"), "fontColor": color("#1F2937")}}]
    return vc


STYLE = {
    "card": {"labels": [{"properties": {"color": color(NAVY), "fontSize": lit("24D")}}],
             "categoryLabels": [{"properties": {"show": lit("true"), "color": color(GREY)}}]},
    "slicer": {"data": [{"properties": {"mode": lit("'Dropdown'")}}], "header": [{"properties": {"show": lit("true")}}]},
    "chart": {"dataPoint": [{"properties": {"fill": color(NAVY)}}],
              "categoryAxis": [{"properties": {"showAxisTitle": lit("false")}}],
              "valueAxis": [{"properties": {"showAxisTitle": lit("false")}}]},
}


def container(pos, single):
    x, y, w, h = pos
    cfg = {"name": uuid.uuid4().hex[:20], "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": 0, "width": w, "height": h}}],
           "singleVisual": single}
    return {"x": x, "y": y, "z": 0, "width": w, "height": h, "config": json.dumps(cfg), "filters": "[]"}


def visual(vtype, pos, roles, title=None, sort=None):
    """roles: {role: [(table, name, is_measure)]}; sort: (table, name, is_measure, direction)."""
    select, projections, tables = [], {}, set()
    for role, fields in roles.items():
        for table, name, is_measure in fields:
            ref = f"{table}.{name}"
            select.append({**field(table, name, is_measure), "Name": ref})
            projections.setdefault(role, []).append({"queryRef": ref})
            tables.add(table)
    query = {"Version": 2, "From": [{"Name": ALIAS[t], "Entity": t, "Type": 0} for t in sorted(tables)], "Select": select}
    if sort:
        query["OrderBy"] = [{"Direction": sort[3], "Expression": field(sort[0], sort[1], sort[2])}]
    if vtype in STYLE:
        objects = dict(STYLE[vtype])
    elif vtype in ("donutChart", "tableEx"):
        objects = {}
    else:
        objects = dict(STYLE["chart"])
        if vtype != "lineChart":
            objects["labels"] = [{"properties": {"show": lit("true")}}]
    return container(pos, {"visualType": vtype, "projections": projections, "prototypeQuery": query,
                           "drillFilterOtherVisuals": True, "objects": objects, "vcObjects": frame(title)})


def textbox(text, pos):
    run = {"value": text, "textStyle": {"fontSize": "20pt", "fontWeight": "bold", "color": "#FFFFFF"}}
    return container(pos, {"visualType": "textbox", "drillFilterOtherVisuals": True,
                           "objects": {"general": [{"properties": {"paragraphs": [{"textRuns": [run]}]}}]},
                           "vcObjects": frame(fill=NAVY)})


def cards(names, y=80):
    width = 1240 // len(names)
    return [visual("card", (20 + i * width, y, width - 10, 95), {"Values": [("Orders", n, True)]}) for i, n in enumerate(names)]


def header(title):
    return [textbox(title, (20, 10, 710, 60)),
            visual("slicer", (740, 10, 250, 60), {"Values": [("Date", "Year", False)]}),
            visual("slicer", (1000, 10, 260, 60), {"Values": [("State", "region", False)]})]


def build_report():
    m = lambda name: ("Orders", name, True)
    month = ("Date", "Month Start", False)
    page1 = [*header("Olist Sales Overview"),
             *cards(["Total Revenue", "Total Orders", "Avg Order Value", "Avg Review Score", "Late Delivery %"]),
             visual("lineChart", (20, 185, 520, 250), {"Category": [month], "Y": [m("Total Revenue")]},
                    "Monthly revenue trend", ("Date", "Month Start", False, 1)),
             visual("tableEx", (550, 185, 430, 250), {"Values": [month, m("Total Revenue"), m("MoM Growth %"), m("Revenue YTD")]},
                    "Monthly performance (MoM and YTD)", ("Date", "Month Start", False, 1)),
             visual("donutChart", (990, 185, 270, 250), {"Category": [("Orders", "payment_type", False)], "Y": [m("Total Revenue")]},
                    "Revenue by payment type"),
             visual("clusteredBarChart", (20, 445, 620, 265), {"Category": [("Orders", "category", False)], "Y": [m("Total Revenue")]},
                    "Revenue by category", ("Orders", "Total Revenue", True, 2)),
             visual("clusteredBarChart", (650, 445, 610, 265), {"Category": [("State", "state_name", False)], "Y": [m("Total Revenue")]},
                    "Revenue by state", ("Orders", "Total Revenue", True, 2))]
    page2 = [*header("Delivery Performance and Customer Reviews"),
             *cards(["Late Delivery %", "Avg Delivery Days", "Avg Review Score", "Bad Review %", "Repeat Customer Orders %"]),
             visual("clusteredColumnChart", (20, 185, 410, 250), {"Category": [("Orders", "delivery_status", False)], "Y": [m("Avg Review Score")]},
                    "Avg review: late vs on time"),
             visual("clusteredColumnChart", (440, 185, 410, 250), {"Category": [("Orders", "delivery_bucket", False)], "Y": [m("Avg Review Score")]},
                    "Avg review by delivery time", ("Orders", "delivery_bucket", False, 1)),
             visual("clusteredColumnChart", (860, 185, 400, 250), {"Category": [("State", "region", False)], "Y": [m("Late Delivery %")]},
                    "Late delivery % by region", ("Orders", "Late Delivery %", True, 2)),
             visual("lineChart", (20, 445, 620, 265), {"Category": [month], "Y": [m("Late Delivery %")]},
                    "Late delivery % trend", ("Date", "Month Start", False, 1)),
             visual("tableEx", (650, 445, 610, 265), {"Values": [("State", "state_name", False), m("Total Orders"), m("Avg Delivery Days"),
                                                                 m("Late Delivery %"), m("Avg Review Score")]}, "State scorecard")]
    page_cfg = json.dumps({"objects": {"background": [{"properties": {"color": color(PAGE_BG), "transparency": lit("0D")}}]}})
    sections = [{"name": f"ReportSection{i}", "displayName": title, "ordinal": i, "displayOption": 1, "width": 1280, "height": 720,
                 "filters": "[]", "config": page_cfg, "visualContainers": visuals}
                for i, (title, visuals) in enumerate([("Sales Overview", page1), ("Delivery & Reviews", page2)])]
    report = {"config": json.dumps({"version": "5.43", "themeCollection": {}, "activeSectionIndex": 0}),
              "layoutOptimization": 0, "sections": sections}
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / "report.json").write_text(json.dumps(report, indent=2))
    (REPORT / "definition.pbir").write_text(json.dumps(
        {"version": "1.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}, "byConnection": None}}, indent=2))


def build_project_files():
    (ROOT / f"{NAME}.pbip").write_text(json.dumps(
        {"version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}], "settings": {"enableAutoRecovery": True}}, indent=2))
    for folder, kind in ((MODEL, "SemanticModel"), (REPORT, "Report")):
        (folder / ".platform").write_text(json.dumps({
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
            "metadata": {"type": kind, "displayName": NAME},
            "config": {"version": "2.0", "logicalId": str(uuid.uuid4())}}, indent=2))
    lines = ["# DAX measures", ""] + [f"```\n{name} = {dax}\n```\n" for name, (dax, _) in MEASURES.items()]
    (ROOT / "DAX_MEASURES.md").write_text("\n".join(lines))


if __name__ == "__main__":
    rows = build_data()
    build_model()
    build_report()
    build_project_files()
    print(f"Power BI project ready: {ROOT / (NAME + '.pbip')}  ({rows:,} order rows, {len(MEASURES)} DAX measures)")
