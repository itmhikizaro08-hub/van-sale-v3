"""PDF Invoice generation using ReportLab."""
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT


def generate_invoice_pdf(sale, company: dict) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=15*mm, leftMargin=15*mm,
                            topMargin=15*mm, bottomMargin=15*mm)

    styles = getSampleStyleSheet()
    BRAND = colors.HexColor('#2563EB')
    DARK = colors.HexColor('#1e293b')
    LIGHT_GRAY = colors.HexColor('#f1f5f9')

    title_style = ParagraphStyle('title', fontSize=22, textColor=BRAND, spaceAfter=2,
                                  fontName='Helvetica-Bold')
    sub_style = ParagraphStyle('sub', fontSize=9, textColor=colors.HexColor('#64748b'))
    heading_style = ParagraphStyle('heading', fontSize=11, textColor=DARK,
                                    fontName='Helvetica-Bold', spaceAfter=4)
    normal = ParagraphStyle('normal2', fontSize=9, textColor=DARK)
    right_style = ParagraphStyle('right', fontSize=9, alignment=TA_RIGHT)

    story = []

    # ── Header ─────────────────────────────────────────────────────────────────
    header_data = [
        [Paragraph(company['name'], title_style),
         Paragraph(f'<b>INVOICE</b>', ParagraphStyle('inv', fontSize=18, textColor=BRAND,
                                                       alignment=TA_RIGHT, fontName='Helvetica-Bold'))],
        [Paragraph(f"{company['address']}<br/>{company['phone']}<br/>{company['email']}", sub_style),
         Paragraph(f'<b>{sale.invoice_number}</b>', ParagraphStyle('invnum', fontSize=12,
                                                                     alignment=TA_RIGHT, fontName='Helvetica-Bold'))]
    ]
    header_table = Table(header_data, colWidths=[100*mm, 80*mm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(header_table)
    story.append(HRFlowable(width='100%', thickness=1.5, color=BRAND))
    story.append(Spacer(1, 6*mm))

    # ── Bill To / Invoice Info ─────────────────────────────────────────────────
    date_str = sale.sale_date.strftime('%d %B %Y') if sale.sale_date else ''
    info_data = [
        [Paragraph('<b>BILL TO</b>', heading_style),
         Paragraph('<b>INVOICE DETAILS</b>', heading_style)],
        [Paragraph(f"<b>{sale.customer.name}</b><br/>"
                   f"{sale.customer.phone or ''}<br/>{sale.customer.address or ''}", normal),
         Paragraph(f"Date: {date_str}<br/>"
                   f"Payment: {sale.payment_method.replace('_',' ').title()}<br/>"
                   f"Status: {sale.payment_status.upper()}", normal)]
    ]
    info_table = Table(info_data, colWidths=[90*mm, 90*mm])
    info_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (-1, 0), LIGHT_GRAY),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 8*mm))

    # ── Items Table ────────────────────────────────────────────────────────────
    col_headers = ['#', 'Product', 'Qty', 'Unit Price', 'Disc%', 'Total']
    rows = [col_headers]
    for i, item in enumerate(sale.items, 1):
        rows.append([
            str(i),
            item.product.product_name if item.product else '',
            str(item.quantity),
            f'GHS {item.unit_price:.2f}',
            f'{item.discount_percent:.0f}%',
            f'GHS {item.line_total:.2f}'
        ])

    items_table = Table(rows, colWidths=[10*mm, 70*mm, 15*mm, 28*mm, 15*mm, 28*mm])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), BRAND),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, -1), 8.5),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#cbd5e1')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 6*mm))

    # ── Totals ─────────────────────────────────────────────────────────────────
    totals_data = [
        ['', 'Subtotal:', f'GHS {sale.subtotal:.2f}'],
        ['', f'Discount ({sale.discount_percent:.0f}%):', f'- GHS {sale.discount_amount:.2f}'],
        ['', f'Tax ({sale.tax_percent:.0f}%):', f'GHS {sale.tax_amount:.2f}'],
        ['', 'TOTAL:', f'GHS {sale.total_amount:.2f}'],
        ['', 'Amount Paid:', f'GHS {sale.amount_paid:.2f}'],
        ['', 'Balance Due:', f'GHS {sale.balance_due:.2f}'],
    ]
    totals_table = Table(totals_data, colWidths=[90*mm, 50*mm, 40*mm])
    totals_table.setStyle(TableStyle([
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('FONTNAME', (1, 3), (-1, 3), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (1, 3), (-1, 3), BRAND),
        ('TEXTCOLOR', (1, 3), (-1, 3), colors.white),
        ('BACKGROUND', (1, 5), (-1, 5), colors.HexColor('#fef9c3')),
        ('FONTNAME', (1, 5), (-1, 5), 'Helvetica-Bold'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (1, 0), (-1, -1), 8),
        ('RIGHTPADDING', (2, 0), (-1, -1), 8),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 10*mm))

    # ── Footer ─────────────────────────────────────────────────────────────────
    story.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#cbd5e1')))
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph('Thank you for your business!',
                            ParagraphStyle('footer', fontSize=9, textColor=colors.HexColor('#64748b'),
                                           alignment=TA_CENTER)))

    doc.build(story)
    return buffer.getvalue()


def generate_van_stock_statement_pdf(van, rep, product, company: dict, start: str, end: str,
                                       current_stock: list, current_total_qty: float,
                                       current_total_value: float, rows: list,
                                       show_value: bool = True) -> bytes:
    """current_stock: list of VanStock rows (already scoped to the one product
    when `product` is set). rows: list of {'date','type','product','qty','reference'}
    from services.statements.van_stock_ledger_rows(). Unlike the money-based
    customer/supplier statement, there's no single balance column — a van
    holds many different products at once."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=15*mm, leftMargin=15*mm,
                            topMargin=15*mm, bottomMargin=15*mm)

    BRAND = colors.HexColor('#2563EB')
    DARK = colors.HexColor('#1e293b')
    LIGHT_GRAY = colors.HexColor('#f1f5f9')

    title_style = ParagraphStyle('title', fontSize=22, textColor=BRAND, spaceAfter=2,
                                  fontName='Helvetica-Bold')
    sub_style = ParagraphStyle('sub', fontSize=9, textColor=colors.HexColor('#64748b'))
    heading_style = ParagraphStyle('heading', fontSize=11, textColor=DARK,
                                    fontName='Helvetica-Bold', spaceAfter=4)
    normal = ParagraphStyle('normal2', fontSize=9, textColor=DARK)

    story = []

    # ── Header ─────────────────────────────────────────────────────────────────
    van_label = van.van_number + (f' ({van.registration_number})' if van.registration_number else '')
    header_data = [
        [Paragraph(company['name'], title_style),
         Paragraph('<b>VAN STOCK STATEMENT</b>', ParagraphStyle('stmt', fontSize=16, textColor=BRAND,
                                                          alignment=TA_RIGHT, fontName='Helvetica-Bold'))],
        [Paragraph(f"{company['address']}<br/>{company['phone']}<br/>{company['email']}", sub_style),
         Paragraph(f'{start} to {end}', ParagraphStyle('period', fontSize=11,
                                                          alignment=TA_RIGHT, fontName='Helvetica-Bold'))]
    ]
    header_table = Table(header_data, colWidths=[100*mm, 80*mm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(header_table)
    story.append(HRFlowable(width='100%', thickness=1.5, color=BRAND))
    story.append(Spacer(1, 6*mm))

    # ── Rep / Van / Current Totals ────────────────────────────────────────────
    subtitle = f'{rep.full_name} — {van_label}' + (f' — {product.product_name}' if product else '')
    info_data = [
        [Paragraph('<b>REP / VAN</b>', heading_style),
         Paragraph('<b>CURRENT UNITS ON VAN</b>', heading_style)],
        [Paragraph(subtitle, normal),
         Paragraph(f"{current_total_qty:g}", ParagraphStyle('units', fontSize=12,
                                                              fontName='Helvetica-Bold', textColor=DARK))]
    ]
    info_table = Table(info_data, colWidths=[110*mm, 70*mm])
    info_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (-1, 0), LIGHT_GRAY),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 8*mm))

    # ── Current Stock Table ───────────────────────────────────────────────────
    story.append(Paragraph('<b>CURRENT STOCK</b>', heading_style))
    stock_headers = ['Product', 'Qty'] + (['Value'] if show_value else [])
    stock_rows = [stock_headers]
    for vs in current_stock:
        row = [vs.product.product_name if vs.product else '', f'{vs.quantity:g}']
        if show_value:
            row.append(f'GHS {vs.quantity * (vs.product.cost_price if vs.product else 0):.2f}')
        stock_rows.append(row)
    if not current_stock:
        stock_rows.append(['No stock currently held.', '', ''] if show_value else ['No stock currently held.', ''])

    stock_col_widths = [110*mm, 30*mm, 40*mm] if show_value else [140*mm, 40*mm]
    stock_table = Table(stock_rows, colWidths=stock_col_widths)
    stock_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), BRAND),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, -1), 8.5),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#cbd5e1')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(stock_table)
    story.append(Spacer(1, 8*mm))

    # ── Movement Ledger ────────────────────────────────────────────────────────
    story.append(Paragraph('<b>MOVEMENT HISTORY</b>', heading_style))
    col_headers = ['Date', 'Type', 'Product', 'Qty', 'Reference']
    table_rows = [col_headers]
    for r in rows:
        qty_str = f"+{r['qty']:g}" if r['qty'] > 0 else f"{r['qty']:g}"
        table_rows.append([r['date'][:10], r['type'], r['product'], qty_str, r['reference']])
    if not rows:
        table_rows.append(['', '', 'No movements in this period', '', ''])

    ledger_table = Table(table_rows, colWidths=[22*mm, 20*mm, 60*mm, 15*mm, 63*mm])
    ledger_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), BRAND),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#cbd5e1')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(ledger_table)
    story.append(Spacer(1, 10*mm))

    # ── Footer ─────────────────────────────────────────────────────────────────
    story.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#cbd5e1')))
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph('Generated from Van Sales V3 ERP',
                            ParagraphStyle('footer3', fontSize=9, textColor=colors.HexColor('#64748b'),
                                           alignment=TA_CENTER)))

    doc.build(story)
    return buffer.getvalue()


def generate_statement_pdf(entity_label: str, entity: dict, company: dict, start: str, end: str,
                            opening_balance: float, rows: list, closing_balance: float) -> bytes:
    """entity_label: 'Customer' or 'Supplier'. entity: {'name','code','phone','email'}.
    rows: list of {'date','description','debit','credit','balance'}."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=15*mm, leftMargin=15*mm,
                            topMargin=15*mm, bottomMargin=15*mm)

    BRAND = colors.HexColor('#2563EB')
    DARK = colors.HexColor('#1e293b')
    LIGHT_GRAY = colors.HexColor('#f1f5f9')

    title_style = ParagraphStyle('title', fontSize=22, textColor=BRAND, spaceAfter=2,
                                  fontName='Helvetica-Bold')
    sub_style = ParagraphStyle('sub', fontSize=9, textColor=colors.HexColor('#64748b'))
    heading_style = ParagraphStyle('heading', fontSize=11, textColor=DARK,
                                    fontName='Helvetica-Bold', spaceAfter=4)
    normal = ParagraphStyle('normal2', fontSize=9, textColor=DARK)

    story = []

    # ── Header ─────────────────────────────────────────────────────────────────
    header_data = [
        [Paragraph(company['name'], title_style),
         Paragraph(f'<b>STATEMENT</b>', ParagraphStyle('stmt', fontSize=18, textColor=BRAND,
                                                          alignment=TA_RIGHT, fontName='Helvetica-Bold'))],
        [Paragraph(f"{company['address']}<br/>{company['phone']}<br/>{company['email']}", sub_style),
         Paragraph(f'{start} to {end}', ParagraphStyle('period', fontSize=11,
                                                          alignment=TA_RIGHT, fontName='Helvetica-Bold'))]
    ]
    header_table = Table(header_data, colWidths=[100*mm, 80*mm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(header_table)
    story.append(HRFlowable(width='100%', thickness=1.5, color=BRAND))
    story.append(Spacer(1, 6*mm))

    # ── Entity / Opening Balance ──────────────────────────────────────────────
    info_data = [
        [Paragraph(f'<b>{entity_label.upper()}</b>', heading_style),
         Paragraph('<b>OPENING BALANCE</b>', heading_style)],
        [Paragraph(f"<b>{entity['name']}</b><br/>{entity.get('code','')}<br/>"
                   f"{entity.get('phone','') or ''}<br/>{entity.get('email','') or ''}", normal),
         Paragraph(f"GHS {opening_balance:.2f}", ParagraphStyle('opening', fontSize=12,
                                                                  fontName='Helvetica-Bold', textColor=DARK))]
    ]
    info_table = Table(info_data, colWidths=[90*mm, 90*mm])
    info_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (-1, 0), LIGHT_GRAY),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 8*mm))

    # ── Ledger Table ───────────────────────────────────────────────────────────
    col_headers = ['Date', 'Description', 'Debit', 'Credit', 'Balance']
    table_rows = [col_headers]
    for r in rows:
        table_rows.append([
            r['date'][:10],
            r['description'],
            f"{r['debit']:.2f}" if r['debit'] else '',
            f"{r['credit']:.2f}" if r['credit'] else '',
            f"{r['balance']:.2f}",
        ])
    if not rows:
        table_rows.append(['', 'No transactions in this period', '', '', f'{closing_balance:.2f}'])

    ledger_table = Table(table_rows, colWidths=[25*mm, 80*mm, 25*mm, 25*mm, 25*mm])
    ledger_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), BRAND),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, -1), 8.5),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#cbd5e1')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(ledger_table)
    story.append(Spacer(1, 6*mm))

    # ── Closing Balance ────────────────────────────────────────────────────────
    total_debit = sum(r['debit'] for r in rows)
    total_credit = sum(r['credit'] for r in rows)
    totals_data = [
        ['', 'Total Debits:', f'GHS {total_debit:.2f}'],
        ['', 'Total Credits:', f'GHS {total_credit:.2f}'],
        ['', 'CLOSING BALANCE:', f'GHS {closing_balance:.2f}'],
    ]
    totals_table = Table(totals_data, colWidths=[90*mm, 50*mm, 40*mm])
    totals_table.setStyle(TableStyle([
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (1, 2), (-1, 2), 'Helvetica-Bold'),
        ('BACKGROUND', (1, 2), (-1, 2), BRAND),
        ('TEXTCOLOR', (1, 2), (-1, 2), colors.white),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (1, 0), (-1, -1), 8),
        ('RIGHTPADDING', (2, 0), (-1, -1), 8),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 10*mm))

    # ── Footer ─────────────────────────────────────────────────────────────────
    story.append(HRFlowable(width='100%', thickness=0.5, color=colors.HexColor('#cbd5e1')))
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph('Thank you for your business!',
                            ParagraphStyle('footer2', fontSize=9, textColor=colors.HexColor('#64748b'),
                                           alignment=TA_CENTER)))

    doc.build(story)
    return buffer.getvalue()
