

import os
import io
from datetime import datetime

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    Image,
)
from reportlab.lib.utils import ImageReader

# === timezone Rome (Europe/Rome) ===
try:
    from zoneinfo import ZoneInfo  # stdlib (Py3.9+)
    TZ_ROME = ZoneInfo("Europe/Rome")
except Exception:
    TZ_ROME = None 

def now_rome_str() -> str:
    """Возвращает текущие дата/время по Риму в формате dd/mm/yy HH:MM."""
    if TZ_ROME:
        dt = datetime.now(TZ_ROME)
    else:
        dt = datetime.now()
    return dt.strftime("%d/%m/%y %H:%M")

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

try:
    pdfmetrics.registerFont(TTFont("PTMono", "fonts/PTMono-Regular.ttf"))
    _PTMONO = "PTMono"
except Exception:
    _PTMONO = "Courier"  


ASK_CLIENTE, ASK_IMPORTO, ASK_TAN, ASK_TAEG, ASK_DURATA = range(5)

TOKEN = os.getenv("BOT_TOKEN")

MAIN_KB = ReplyKeyboardMarkup(
    [
        [KeyboardButton("Сделать контракт")],
        [KeyboardButton("Комиссия 1"), KeyboardButton("Комиссия 2"), KeyboardButton("Комиссия 3")],
    ],
    resize_keyboard=True,
)

# ---------- НАСТРОЙКИ ПОДПИСЕЙ ----------
SIG_TARGET_W   = 72 * mm    # желаемая ширина PNG подписи
SIG_MAX_H      = 34 * mm    # ограничение по высоте PNG подписи
SIG_ROW_H      = 36 * mm    # высота строки, где стоят подписи
SIG_BOTTOM_PAD = -8         # поджать подпись к линии (меньше — ближе)
SIG_LINE_THICK = 1.2        # толщина линии подписи



def fmt_eur(v: float) -> str:
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"€ {s}"

def parse_num(txt: str) -> float:
    t = txt.strip().replace(" ", "")
    t = t.replace(".", "").replace(",", ".")
    return float(t)

def monthly_payment(principal: float, tan_percent: float, months: int) -> float:
    if months <= 0:
        return 0.0
    r = (tan_percent / 100.0) / 12.0
    if r == 0:
        return principal / months
    return principal * (r / (1 - (1 + r) ** (-months)))


def sig_image(path: str, target_w=SIG_TARGET_W, max_h=SIG_MAX_H):
    if not os.path.exists(path):
        return None
    ir = ImageReader(path)
    iw, ih = ir.getSize()
    ratio = ih / float(iw)
    w = target_w
    h = w * ratio
    if h > max_h:
        h = max_h
        w = h / ratio
    return Image(path, width=w, height=h)


def draw_border_and_pagenum(canv, doc):
    width, height = A4
    canv.saveState()
    outer_margin = 10 * mm
    inner_offset = 6
    line_w = 2

    canv.setStrokeColor(colors.red)
    canv.setLineWidth(line_w)
    canv.rect(outer_margin, outer_margin, width - 2*outer_margin, height - 2*outer_margin, stroke=1, fill=0)
    canv.rect(
        outer_margin + inner_offset,
        outer_margin + inner_offset,
        width - 2*(outer_margin + inner_offset),
        height - 2*(outer_margin + inner_offset),
        stroke=1,
        fill=0,
    )

    canv.setFont(_PTMONO, 9)
    canv.setFillColor(colors.black)
    canv.drawCentredString(width/2.0, 5*mm, str(canv.getPageNumber()))
    canv.restoreState()


def build_pdf(values: dict) -> bytes:
    """
    values: {
        "cliente": str,
        "importo": float,
        "tan": float,
        "taeg": float,
        "durata": int
    }
    """
    cliente = values.get("cliente", "").strip()
    importo = values["importo"]
    tan = values["tan"]
    taeg = values["taeg"]
    durata = values["durata"]

    rata = monthly_payment(importo, tan, durata)
    interessi = rata * durata - importo
    totale = importo + interessi

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Small", fontName=_PTMONO, fontSize=9.5, leading=11))
    styles.add(ParagraphStyle(name="Tiny",  fontName=_PTMONO, fontSize=8.3, leading=10))
    styles.add(ParagraphStyle(name="H1",    fontSize=14,  leading=16, spaceAfter=6))
    styles.add(ParagraphStyle(name="H2",    fontSize=11,  leading=13, spaceAfter=4, spaceBefore=4))
    styles.add(ParagraphStyle(name="Body",  fontName=_PTMONO, fontSize=10.5, leading=12.5))
    styles.add(ParagraphStyle(name="SigHead", fontName=_PTMONO, fontSize=12, leading=14, alignment=1))
    styles.add(ParagraphStyle(name="RightSmall", fontName=_PTMONO, fontSize=9.2, leading=11, alignment=2))  # справа

    story = []


    logo_bda = "banca_dalba_logo.png"
    logo_bcc = "bcc_logo.png"
    logo_2fin = "2fin_logo.png"
    logos_row = []
    for p, w in [(logo_bda, 65 * mm), (logo_bcc, 18 * mm), (logo_2fin, 18 * mm)]:
        if os.path.exists(p):
            logos_row.append(Image(p, width=w, height=16 * mm))
        else:
            logos_row.append(Paragraph("", styles["Small"]))
    if any(os.path.exists(p) for p in [logo_bda, logo_bcc, logo_2fin]):
        hdr = Table([logos_row], colWidths=[100 * mm, 25 * mm, 25 * mm])
        hdr.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (1, 0), (2, 0), "RIGHT"),
        ]))
        story.append(hdr)
        story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("<b>Banca d'Alba — Credito Cooperativo</b>", styles["H1"]))
    story.append(Paragraph("Sede legale: Via Cavour 4, 12051 Alba (CN)", styles["Small"]))
    story.append(Paragraph("<b>Offerta preliminare di credito (pre-approvata)</b>", styles["H1"]))
    story.append(Spacer(1, 2 * mm))

    story.append(Paragraph(f"<b>Cliente:</b> {cliente or '____________________'}", styles["Body"]))
    story.append(Paragraph("Comunicazioni e gestione pratica: <b>2FIN SRL</b> (Agente in attivita finanziaria — OAM A15135)", styles["Small"]))
    story.append(Paragraph("Contatto: Telegram @operatore_2fin", styles["Small"]))


    story.append(Paragraph(f"<i>Creato: {now_rome_str()} (Europa/Roma)</i>", styles["RightSmall"]))
    story.append(Spacer(1, 3 * mm))


    data = [
        ["Parametro", "Dettagli"],
        ["Importo del credito", fmt_eur(importo)],
        ["Tasso fisso (TAN)", f"{tan:.2f} %"],
        ["TAEG indicativo", f"{taeg:.2f} %"],
        ["Durata", f"{durata} mesi"],
        ["Rata mensile*", fmt_eur(rata)],
        ["Spese di istruttoria", "€ 0"],
        ["Commissione incasso", "€ 0"],
        ["Contributo amministrativo", "€ 0"],
        ["Premio assicurativo", "€ 140 (se richiesto)"],
        ["Erogazione fondi", "30-60 min dopo la firma del contratто finale"],
    ]
    t = Table(data, colWidths=[75 * mm, 100 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ececec")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("FONTNAME", (0, 1), (-1, -1), _PTMONO),
    ]))
    story.append(t)
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("<i>*Rata calcolata alla data dell'offerta.</i>", styles["Tiny"]))
    story.append(Spacer(1, 4 * mm))


    story.append(Paragraph("<b>Vantaggi</b>", styles["H2"]))
    vantaggi = [
        "Possibilita di sospendere fino a 3 rate",
        "Estinzione anticipata senza penali",
        "Riduzione del TAN -0,10 p.p. ogni 12 mesi puntuali (fino a 5,95%)",
        "Sospensione straordinaria delle rate in caso di perdita del lavoro (previo consenso della banca)",
    ]
    for s in vantaggi:
        story.append(Paragraph("• " + s, styles["Small"]))

    story.append(Paragraph("<b>Penali e interessi di mora</b>", styles["H2"]))
    penali = [
        "Ritardo oltre 5 giorni: TAN + 2 p.p.",
        "Sollecito: €10 cartaceo / €5 digitale",
        "2 rate non pagate: risoluzione del contratто e recupero crediti",
        "Penale per risoluzione anticipata solo in caso di violazione delle condizioni contrattuali",
    ]
    for s in penali:
        story.append(Paragraph("• " + s, styles["Small"]))

    story.append(Paragraph("<b>Comunicazioni e pagamento servizi 2FIN</b>", styles["H2"]))
    comunicazioni = [
        "Tutte le comunicazioni tra banca e cliente gestite solo tramite 2FIN SRL.",
        "Contratto e allegati inviati in PDF via Telegram.",
        "Servizi 2FIN — quota fissa €100 (non commissione bancaria), pagamento via SEPA / SEPA Instant al conto del commercialista indipendente.",
    ]
    for s in comunicazioni:
        story.append(Paragraph("• " + s, styles["Small"]))

    story.append(PageBreak())


    story.append(Paragraph("<b>Riepilogo economico</b>", styles["H2"]))
    riepilogo = [
        ["Importo del credito", fmt_eur(importo)],
        ["Interessi stimati (durata)", fmt_eur(interessi)],
        ["Spese una tantum", "€ 0"],
        ["Commissione incasso", "€ 0"],
        ["Totale dovuto (stima)", fmt_eur(totale)],
        ["Durata", f"{durata} mesi"],
    ]
    rt = Table(riepilogo, colWidths=[85 * mm, 85 * mm])
    rt.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("FONTNAME", (0, 0), (-1, -1), _PTMONO),
    ]))
    story.append(rt)
    story.append(Spacer(1, 3 * mm))

    story.append(Paragraph("<b>Informazioni legali (estratto)</b>", styles["H2"]))
    legal = [
        "L'offerta e' preliminare e pre-approvata: con l'accettazione del cliente diventa vincolante alle condizioni sopra descritte.",
        "Il TAEG e' indicativo e puo' variare alla data di firma del contratto.",
        "Il cliente ha diritto a ricevere SECCI e piano di ammortamento completo dopo la firma.",
        "Il cliente ha diritto di recesso nei termini di legge.",
        "Reclami tramite 2FIN o Arbitro Bancario Finanziario (ABF).",
        "Invio del contratто via Telegram considerato equivalente a e-mail o posta cartacea.",
        "Pagamento servizi 2FIN solo via SEPA/SEPA Instant al commercialista indipendente.",
        "Trattamento dati personali secondo la normativa vigente.",
    ]
    for s in legal:
        story.append(Paragraph("• " + s, styles["Small"]))

    story.append(Spacer(1, 8 * mm))


    sig_minetti = sig_image("minettisign.png")
    sig_rossi   = sig_image("giuseppesign.png")

    head_l = Paragraph("Firma Cliente", styles["SigHead"])
    head_c = Paragraph("Firma Rappresentante<br/>Banca d'Alba", styles["SigHead"])
    head_r = Paragraph("Firma Rappresentante<br/>2FIN", styles["SigHead"])

    sign_col_widths = [50*mm, 65*mm, 65*mm]

    sign_table = Table(
        [
            [head_l, head_c, head_r],
            ["",     sig_rossi or "", sig_minetti or ""],
            ["",     "",              ""],
            ["", "Rapp. banca: Giuseppe Rossi", "Rapp. 2FIN: Alessandro Minetti"],
        ],
        colWidths=sign_col_widths,
        rowHeights=[None, SIG_ROW_H, 10*mm, None],
        hAlign="CENTER",
    )

    ts = [
        ("FONTNAME", (0, 0), (-1, -1), _PTMONO),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 1), (-1, 1), "BOTTOM"),
        ("BOTTOMPADDING", (0, 1), (-1, 1), SIG_BOTTOM_PAD),
        ("TOPPADDING", (0, 1), (-1, 1), 0),
        ("LINEBELOW", (0, 1), (0, 1), SIG_LINE_THICK, colors.black),
        ("LINEBELOW", (1, 1), (1, 1), SIG_LINE_THICK, colors.black),
        ("LINEBELOW", (2, 1), (2, 1), SIG_LINE_THICK, colors.black),
        ("FONTSIZE", (1, 3), (2, 3), 9.2),
        ("RIGHTPADDING", (1, 3), (1, 3), 12),
        ("LEFTPADDING",  (2, 3), (2, 3), 12),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",(0, 0), (-1, -1), 6),
    ]
    sign_table.setStyle(TableStyle(ts))
    story.append(sign_table)


    stamp_path = "stampaalba.png"
    if os.path.exists(stamp_path):
        story.append(Spacer(1, 5 * mm))
        stamp_img = Image(stamp_path, width=120, height=120)
        stamp_tbl = Table([[stamp_img]], colWidths=[doc.width])
        stamp_tbl.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "RIGHT")]))
        story.append(stamp_tbl)


    doc.build(story, onFirstPage=draw_border_and_pagenum, onLaterPages=draw_border_and_pagenum)
    buf.seek(0)
    return buf.read()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Выберите действие:", reply_markup=MAIN_KB)

async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "Сделать контракт":
        await update.message.reply_text("Введите имя и фамилию клиента (например: Mario Rossi)")
        return ASK_CLIENTE
    elif text in {"Комиссия 1", "Комиссия 2", "Комиссия 3"}:
        await update.message.reply_text("Скоро добавим 🔧")
        return ConversationHandler.END
    else:
        await update.message.reply_text("Нажмите одну из кнопок ниже.", reply_markup=MAIN_KB)
        return ConversationHandler.END

async def ask_cliente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("Пожалуйста, укажите имя и фамилию клиента (например: Mario Rossi).")
        return ASK_CLIENTE
    context.user_data["cliente"] = name
    await update.message.reply_text("Введите сумму кредита (Importo), например: 12000 или 12.000,00")
    return ASK_IMPORTO

async def ask_importo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        importo = parse_num(update.message.text)
        if importo <= 0:
            raise ValueError
    except Exception:
        await update.message.reply_text("Пожалуйста, введите корректную сумму (например, 12000).")
        return ASK_IMPORTO
    context.user_data["importo"] = importo
    await update.message.reply_text("Введите TAN в процентах (например, 6.45)")
    return ASK_TAN

async def ask_tan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        tan = parse_num(update.message.text)
        if tan < 0 or tan > 40:
            raise ValueError
    except Exception:
        await update.message.reply_text("Введите корректный TAN (например, 6.45)")
        return ASK_TAN
    context.user_data["tan"] = tan
    await update.message.reply_text("Введите TAEG в процентах (например, 7.98)")
    return ASK_TAEG

async def ask_taeg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        taeg = parse_num(update.message.text)
        if taeg < 0 or taeg > 50:
            raise ValueError
    except Exception:
        await update.message.reply_text("Введите корректный TAEG (например, 7.98)")
        return ASK_TAEG
    context.user_data["taeg"] = taeg
    await update.message.reply_text("Введите срок (Durata) в месяцах (например, 48)")
    return ASK_DURATA

async def ask_durata(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        durata = int(parse_num(update.message.text))
        if durata <= 0 or durata > 180:
            raise ValueError
    except Exception:
        await update.message.reply_text("Введите корректный срок в месяцах (например, 48)")
        return ASK_DURATA
    context.user_data["durata"] = durata

    pdf_bytes = build_pdf(
        {
            "cliente": context.user_data.get("cliente", ""),
            "importo": context.user_data["importo"],
            "tan": context.user_data["tan"],
            "taeg": context.user_data["taeg"],
            "durata": context.user_data["durata"],
        }
    )

    await update.message.reply_document(
        document=InputFile(io.BytesIO(pdf_bytes), filename="Offerta_Preliminare_2FIN.pdf"),
        caption="Готово! Можем внести правки, если нужно.",
    )
    return ConversationHandler.END

def main():
    if not TOKEN:
        raise SystemExit("Укажите токен в переменной окружения BOT_TOKEN")

    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Сделать контракт$"), handle_menu)],
        states={
            ASK_CLIENTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_cliente)],
            ASK_IMPORTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_importo)],
            ASK_TAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_tan)],
            ASK_TAEG: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_taeg)],
            ASK_DURATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_durata)],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.Regex("^(Комиссия 1|Комиссия 2|Комиссия 3)$"), handle_menu))

    app.run_polling()

if __name__ == "__main__":
    main()
