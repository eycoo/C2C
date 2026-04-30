import os
import sqlite3
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.db import get_transactions

OUTPUT_PATH = Path(__file__).parent.parent.parent / "report.pdf"


def _fmt_rp(amount: int) -> str:
    return "Rp " + format(amount, ",d").replace(",", ".")


def generate_pdf_report(phone_number: str) -> str:
    rows: list[sqlite3.Row] = get_transactions(phone_number)

    doc = SimpleDocTemplate(
        str(OUTPUT_PATH),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title",
        parent=styles["Heading1"],
        fontSize=18,
        spaceAfter=6,
        textColor=colors.HexColor("#1a1a2e"),
    )
    sub_style = ParagraphStyle(
        "Sub",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.grey,
        spaceAfter=4,
    )

    elements = []

    # Header
    elements.append(Paragraph("Laporan Keuangan", title_style))
    elements.append(Paragraph(f"Pengguna: {phone_number}", sub_style))
    elements.append(
        Paragraph(f"Dibuat: {datetime.now().strftime('%d %B %Y, %H:%M')}", sub_style)
    )
    elements.append(Spacer(1, 0.5 * cm))

    if not rows:
        elements.append(Paragraph("Belum ada transaksi tercatat.", styles["Normal"]))
        doc.build(elements)
        return str(OUTPUT_PATH)

    # Table
    table_data = [["Tanggal", "Tipe", "Jumlah", "Kategori", "Deskripsi"]]
    total_income = 0
    total_expense = 0

    for row in rows:
        created_at = row["created_at"]
        if isinstance(created_at, str):
            try:
                dt = datetime.fromisoformat(created_at)
                date_str = dt.strftime("%d/%m/%Y %H:%M")
            except ValueError:
                date_str = created_at
        else:
            date_str = str(created_at)

        intent = row["intent"] or "unknown"
        amount = row["amount"] or 0
        category = row["category"] or "-"
        description_text = row["description"] or "-"
        description_paragraph = Paragraph(description_text, styles["Normal"])

        if intent == "income":
            total_income += amount
        elif intent == "expense":
            total_expense += amount

        label_map = {"income": "Pemasukan", "expense": "Pengeluaran", "unknown": "Tidak Diketahui"}
        table_data.append([
            date_str,
            label_map.get(intent, intent),
            _fmt_rp(amount),
            category,
            description_paragraph,
        ])

    col_widths = [3.5 * cm, 2.8 * cm, 3.0 * cm, 3.0 * cm, 5.5 * cm]
    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f4f4")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 0.8 * cm))

    # Footer summary
    net = total_income - total_expense
    net_color = colors.green if net >= 0 else colors.red
    summary_style = ParagraphStyle("Summary", parent=styles["Normal"], fontSize=10, spaceAfter=3)
    bold_style = ParagraphStyle("Bold", parent=styles["Normal"], fontSize=11, spaceAfter=3)

    elements.append(Paragraph("<b>Ringkasan</b>", bold_style))
    elements.append(Paragraph(f"Total Pemasukan: {_fmt_rp(total_income)}", summary_style))
    elements.append(Paragraph(f"Total Pengeluaran: {_fmt_rp(total_expense)}", summary_style))
    elements.append(
        Paragraph(
            f"<b>Saldo Bersih: {_fmt_rp(abs(net))} {'(+)' if net >= 0 else '(-)'}</b>",
            ParagraphStyle("Net", parent=styles["Normal"], fontSize=11, textColor=net_color),
        )
    )

    doc.build(elements)
    return str(OUTPUT_PATH)
