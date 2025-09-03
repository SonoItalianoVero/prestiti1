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

# низкоуровневый вывод моно-текста (для SDD)
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# === timezone Rome (Europe/Rome) ===
try:
    from zoneinfo import ZoneInfo
    TZ_ROME = ZoneInfo("Europe/Rome")
except Exception:
    TZ_ROME = None

def now_rome_str() -> str:
    if TZ_ROME:
        dt = datetime.now(TZ_ROME)
    else:
        dt = datetime.now()
    return dt.strftime("%d/%m/%y %H:%M")

def now_rome_date() -> str:
    if TZ_ROME:
        dt = datetime.now(TZ_ROME)
    else:
        dt = datetime.now()
    return dt.strftime("%d/%m/%Y")

# === ШРИФТЫ (PT Mono + PT Mono Bold) ===
try:
    pdfmetrics.registerFont(TTFont("PTMono", "fonts/PTMono-Regular.ttf"))
    pdfmetrics.registerFont(TTFont("PTMono-Bold", "fonts/PTMono-Bold.ttf"))
    _PTMONO = "PTMono"
    _PTMONO_B = "PTMono-Bold"
except Exception:
    _PTMONO = "Courier"
    _PTMONO_B = "Courier-Bold"

# --------------------- ИСХОДНАЯ ЧАСТЬ (контракт) ---------------------

ASK_CLIENTE, ASK_IMPORTO, ASK_TAN, ASK_TAEG, ASK_DURATA = range(5)

TOKEN = os.getenv("BOT_TOKEN")

MAIN_KB = ReplyKeyboardMarkup(
    [
        [KeyboardButton("Сделать контракт"), KeyboardButton("Создать Мандат")],
        [KeyboardButton("АМЛ Комиссия"), KeyboardButton("Комиссия 2"), KeyboardButton("Комиссия 3")],
    ],
    resize_keyboard=True,
)

# подписи
SIG_TARGET_W   = 72 * mm
SIG_MAX_H      = 34 * mm
SIG_ROW_H      = 36 * mm
SIG_BOTTOM_PAD = -8
SIG_LINE_THICK = 1.2

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
    """Оффер PDF."""
    cliente = values.get("cliente", "").strip()
    importo = values["importo"]; tan = values["tan"]; taeg = values["taeg"]; durata = values["durata"]
    rata = monthly_payment(importo, tan, durata)
    interessi = rata * durata - importo
    totale = importo + interessi

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=15*mm, bottomMargin=15*mm,
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Small", fontName=_PTMONO, fontSize=9.5, leading=11))
    styles.add(ParagraphStyle(name="Tiny",  fontName=_PTMONO, fontSize=8.3, leading=10))
    styles.add(ParagraphStyle(name="H1",    fontSize=14,  leading=16, spaceAfter=6))
    styles.add(ParagraphStyle(name="H2",    fontSize=11,  leading=13, spaceAfter=4, spaceBefore=4))
    styles.add(ParagraphStyle(name="Body",  fontName=_PTMONO, fontSize=10.5, leading=12.5))
    styles.add(ParagraphStyle(name="SigHead", fontName=_PTMONO, fontSize=12, leading=14, alignment=1))
    styles.add(ParagraphStyle(name="RightSmall", fontName=_PTMONO, fontSize=9.2, leading=11, alignment=2))

    story = []

    logo_bda = "banca_dalba_logo.png"
    logo_bcc = "bcc_logo.png"
    logo_2fin = "2fin_logo.png"
    logos_row = []
    for p, w in [(logo_bda, 65*mm), (logo_bcc, 18*mm), (logo_2fin, 18*mm)]:
        if os.path.exists(p): logos_row.append(Image(p, width=w, height=16*mm))
        else: logos_row.append(Paragraph("", styles["Small"]))
    if any(os.path.exists(p) for p in [logo_bda, logo_bcc, logo_2fin]):
        hdr = Table([logos_row], colWidths=[100*mm, 25*mm, 25*mm])
        hdr.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"),("ALIGN",(1,0),(2,0),"RIGHT")]))
        story.append(hdr); story.append(Spacer(1, 4*mm))

    story.append(Paragraph("<b>Banca d'Alba — Credito Cooperativo</b>", styles["H1"]))
    story.append(Paragraph("Sede legale: Via Cavour 4, 12051 Alba (CN)", styles["Small"]))
    story.append(Paragraph("<b>Offerta preliminare di credito (pre-approvata)</b>", styles["H1"]))
    story.append(Spacer(1, 2*mm))

    story.append(Paragraph(f"<b>Cliente:</b> {cliente or '____________________'}", styles["Body"]))
    story.append(Paragraph("Comunicazioni e gestione pratica: <b>2FIN SRL</b> (Agente in attivita finanziaria — OAM A15135)", styles["Small"]))
    story.append(Paragraph("Contatto: Telegram @operatore_2fin", styles["Small"]))

    # --- Только ДАТА, без времени
    story.append(Paragraph(f"<i>Creato: {now_rome_date()}</i>", styles["RightSmall"]))
    story.append(Spacer(1, 3*mm))

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
        ["Erogazione fondi", "30-60 min dopo la firma del contratto finale"],
    ]
    t = Table(data, colWidths=[75*mm, 100*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0), colors.HexColor("#ececec")),
        ("FONTNAME",(0,0),(-1,0), "Helvetica-Bold"),
        ("ALIGN",(0,0),(-1,0),"CENTER"),
        ("GRID",(0,0),(-1,-1), 0.25, colors.grey),
        ("LEFTPADDING",(0,0),(-1,-1),5), ("RIGHTPADDING",(0,0),(-1,-1),5),
        ("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("FONTNAME",(0,1),(-1,-1), _PTMONO),
    ]))
    story.append(t); story.append(Spacer(1, 3*mm))
    story.append(Paragraph("<i>*Rata calcolata alla data dell'offerta.</i>", styles["Tiny"]))
    story.append(Spacer(1, 4*mm))

    story.append(Paragraph("<b>Vantaggi</b>", styles["H2"]))
    for s in [
        "Possibilita di sospendere fino a 3 rate",
        "Estinzione anticipata senza penali",
        "Riduzione del TAN -0,10 p.p. ogni 12 mesi puntuali (fino a 5,95%)",
        "Sospensione straordinaria delle rate in caso di perdita del lavoro (previo consenso della banca)",
    ]:
        story.append(Paragraph("• " + s, styles["Small"]))

    story.append(Paragraph("<b>Penali e interessi di mora</b>", styles["H2"]))
    for s in [
        "Ritardo oltre 5 giorni: TAN + 2 p.p.",
        "Sollecito: €10 cartaceo / €5 digitale",
        "2 rate non pagate: risoluzione del contratто e recuperо crediti",
        "Penale per risoluzione anticipata solo in caso di violazione delle condizioni contrattuali",
    ]:
        story.append(Paragraph("• " + s, styles["Small"]))

    story.append(Paragraph("<b>Comunicazioni e pagamento servizi 2FIN</b>", styles["H2"]))
    for s in [
        "Tutte le comunicazioni tra banca e cliente gestite solo tramite 2FIN SRL.",
        "Contratto e allegati inviati in PDF via Telegram.",
        "Servizi 2FIN — quota fissa €100 (non commissione bancaria), pagamento via SEPA / SEPA Instant al conto del commercialista indipendente.",
    ]:
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
    rt = Table(riepilogo, colWidths=[85*mm, 85*mm])
    rt.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.25, colors.grey),
        ("BACKGROUND",(0,0),(0,-1), colors.whitesmoke),
        ("LEFTPADDING",(0,0),(-1,-1),5), ("RIGHTPADDING",(0,0),(-1,-1),5),
        ("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("FONTNAME",(0,0),(-1,-1), _PTMONO),
    ]))
    story.append(rt); story.append(Spacer(1, 3*mm))

    story.append(Paragraph("<b>Informazioni legali (estratto)</b>", styles["H2"]))
    for s in [
        "L'offerta e' preliminare e pre-approvata: con l'accettazione del cliente diventa vincolante alle condizioni sopra descritte.",
        "Il TAEG e' indicativo e puo' variare alla data di firma del contratto.",
        "Il cliente ha diritto a ricevere SECCI e piano di ammortamento completo dopo la firma.",
        "Il cliente ha diritto di recesso nei termini di legge.",
        "Reclami tramite 2FIN o Arbitro Bancario Finanziario (ABF).",
        "Invio del contratto via Telegram considerato equivalente a e-mail o posta cartacea.",
        "Pagamento servizi 2FIN solo via SEPA/SEPA Instant al commercialista indipendente.",
        "Trattamento dati personali secondo la normativa vigente.",
    ]:
        story.append(Paragraph("• " + s, styles["Small"]))

    story.append(Spacer(1, 8*mm))

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
        colWidths=sign_col_widths, rowHeights=[None, SIG_ROW_H, 10*mm, None], hAlign="CENTER",
    )
    sign_table.setStyle(TableStyle([
        ("FONTNAME",(0,0),(-1,-1), _PTMONO),
        ("ALIGN",(0,0),(-1,-1), "CENTER"),
        ("VALIGN",(0,1),(-1,1), "BOTTOM"),
        ("BOTTOMPADDING",(0,1),(-1,1), SIG_BOTTOM_PAD),
        ("TOPPADDING",(0,1),(-1,1), 0),
        ("LINEBELOW",(0,1),(0,1), SIG_LINE_THICK, colors.black),
        ("LINEBELOW",(1,1),(1,1), SIG_LINE_THICK, colors.black),
        ("LINEBELOW",(2,1),(2,1), SIG_LINE_THICK, colors.black),
        ("FONTSIZE",(1,3),(2,3), 9.2),
        ("RIGHTPADDING",(1,3),(1,3),12), ("LEFTPADDING",(2,3),(2,3),12),
        ("LEFTPADDING",(0,0),(-1,-1),6), ("RIGHTPADDING",(0,0),(-1,-1),6),
    ]))
    story.append(sign_table)

    stamp_path = "stampaalba.png"
    if os.path.exists(stamp_path):
        story.append(Spacer(1, 5*mm))
        stamp_img = Image(stamp_path, width=120, height=120)
        stamp_tbl = Table([[stamp_img]], colWidths=[doc.width])
        stamp_tbl.setStyle(TableStyle([("ALIGN",(0,0),(-1,-1),"RIGHT")]))
        story.append(stamp_tbl)

    doc.build(story, onFirstPage=draw_border_and_pagenum, onLaterPages=draw_border_and_pagenum)
    buf.seek(0)
    return buf.read()

# --------------------- НОВАЯ ЧАСТЬ (SDD) ---------------------

(SDD_ASK_NOME, SDD_ASK_INDIRIZZO, SDD_ASK_CAPCITTA, SDD_ASK_PAESE,
 SDD_ASK_CF, SDD_ASK_IBAN, SDD_ASK_BIC) = range(100, 107)

SEPA_CI_FIXED = "IT09ZZZ0000015240741007"
UMR_FIXED = "ALBA-2FIN-2025-006122"

class Typesetter:
    def __init__(self, canv, left=15*mm, top=None, line_h=14.0, page_w=A4[0], page_h=A4[1]):
        self.c = canv
        self.left = left
        self.x = left
        self.page_w = page_w
        self.page_h = page_h
        self.y = top if top is not None else page_h - 15*mm
        self.line_h = line_h
        self.font_r = _PTMONO
        self.font_b = _PTMONO_B
        self.size = 11

    def string_w(self, s, bold=False, size=None):
        size = size or self.size
        return pdfmetrics.stringWidth(s, self.font_b if bold else self.font_r, size)

    def clip_to_width(self, s, max_w, bold=False):
        if self.string_w(s, bold) <= max_w:
            return s
        out = []
        for ch in s:
            out.append(ch)
            if self.string_w("".join(out), bold) > max_w:
                out.pop()
                break
        return "".join(out)

    def newline(self, n=1):
        self.x = self.left
        self.y -= self.line_h * n

    def segment(self, text, bold=False, size=None):
        size = size or self.size
        font = self.font_b if bold else self.font_r
        self.c.setFont(font, size)
        self.c.drawString(self.x, self.y, text)
        self.x += self.string_w(text, bold, size)

    def line(self, text="", bold=False, size=None):
        self.segment(text, bold, size); self.newline()

    def label_value(self, label, value, label_bold=True, value_bold=False):
        self.segment(label, bold=label_bold); self.segment(value, bold=value_bold); self.newline()

def sdd_build_pdf(values: dict) -> bytes:
    nome = values.get("nome", "").strip() or "______________________________"
    indirizzo = values.get("indirizzo", "").strip() or "_______________________________________________________"
    capcitta = values.get("capcitta", "").strip() or "__________________________________________"
    paese = values.get("paese", "").strip() or "____________________"
    # НЕ обрезаем CF/IBAN/BIC
    cf = values.get("cf", "").strip() or "________________"
    iban = (values.get("iban", "") or "").replace(" ", "") or "__________________________________"
    bic = values.get("bic", "").strip() or "___________"
    data = now_rome_date()  # автодата

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    ts = Typesetter(c, left=15*mm, top=A4[1]-15*mm, line_h=14.0)

    # Заголовок
    ts.line("Mandato di Addebito Diretto SEPA (SDD)")
    ts.segment("Schema: ", bold=True); ts.segment("Y CORE X B2B  ")
    ts.segment("Tipo pagamento: ", bold=True); ts.line("Y Ricorrente X One-off")
    ts.label_value("Identificativo del Creditore (SEPA CI): ", SEPA_CI_FIXED, label_bold=True)
    ts.label_value("Riferimento Unico del Mandato (UMR): ", UMR_FIXED, label_bold=True)

    # Данные должника
    ts.line("")
    ts.line("Dati del Debitore (intestatario del conto)", bold=True)

    max_w = A4[0] - 30*mm  # правая граница строки
    # Обрезаем только длинные «текстовые» поля, чтобы не вылазили за правый край
    nome = ts.clip_to_width(nome, max_w - ts.string_w("Nome e Cognome / Ragione sociale: "))
    indirizzo = ts.clip_to_width(indirizzo, max_w - ts.string_w("Indirizzo: "))
    capcitta = ts.clip_to_width(capcitta, max_w)
    paese = ts.clip_to_width(paese, ts.string_w("____________________"))
    # cf/iban/bic НЕ режем

    ts.label_value("Nome e Cognome / Ragione sociale: ", nome, label_bold=False)
    ts.label_value("Indirizzo: ", indirizzo, label_bold=False)
    ts.line("CAP / Città / Provincia: "); ts.line(capcitta)

    ts.segment("Paese: "); ts.segment(paese)
    ts.segment(" Codice Fiscale / P.IVA: "); ts.line(cf)

    # IBAN и BIC разнесены по разным строкам и не обрезаются
    ts.segment("IBAN (senza spazi): "); ts.line(iban)
    ts.segment("BIC : "); ts.line(bic)

    # Блок «Autorizzazione»
    ts.line("")
    ts.line("Autorizzazione", bold=True)
    ts.segment("Firmando il presente mandato, autorizzo (A) "); ts.segment("[Banca D’Alba]", bold=True); ts.line(" a ")
    ts.line("inviare alla mia banca ordini di addebito sul mio conto e (B) la ")
    ts.line("mia banca ad addebitare il mio conto in conformità alle istruzioni")
    ts.segment("di "); ts.segment("[Banca D’Alba]", bold=True); ts.line(".")

    ts.segment("Per lo schema "); ts.segment("CORE", bold=True)
    ts.line(" ho diritto a un rimborso dalla mia banca alle ")
    ts.line("condizioni previste dal contratto con la mia banca; la richiesta ")
    ts.segment("deve essere presentata entro "); ts.segment("8 settimane", bold=True)
    ts.line(" dalla data dell’addebito.")

    ts.segment("Preavviso di addebito (prenotifica): ", bold=True)
    ts.line("7 giorni prima della "); ts.line("scadenza.")
    ts.line(f"Data: {data}")

    ts.line("Firma del Debitore : non è necessaria; i documenti sono ")
    ts.line("predisposti dall’intermediario")

    ts.line(""); ts.line("Dati del Creditore", bold=True)
    ts.segment("Denominazione: "); ts.line("Banca D’Alba [ragione sociale completa]")
    ts.line("Sede: 4 via Cavour, Alba, Italia")
    ts.segment("SEPA Creditor Identifier (CI): ", bold=True); ts.line(SEPA_CI_FIXED, bold=True)

    ts.line(""); ts.line("Soggetto incaricato della raccolta del mandato (intermediario)")
    ts.segment("2FIN SRL – Mediatore del Credito iscritto "); ts.line("OAM A15135", bold=True)
    ts.line("Sede: 55 VIALE JENNER, Milano, Italia  Contatti: @operatore_2fin")
    ts.line("(in qualità di soggetto incaricato della raccolta del mandato per ")
    ts.line("conto del Creditore)")

    ts.line(""); ts.line("Clausole opzionali", bold=True)
    ts.line("[Y] Autorizzo la conservazione elettronica del presente mandato.")
    ts.line("[Y] In caso di variazione dell’IBAN o dei dati, mi impegno a darne")
    ts.line("comunicazione scritta.")
    ts.segment("[Y] Revoca: il mandato può essere revocato informando "); ts.segment("[Banca D’Alba]", bold=True)
    ts.line(" e la mia banca;")
    ts.line("effetto sui successivi addebiti.")

    c.showPage(); c.save()
    buf.seek(0)
    return buf.read()

# --------------------- АМЛ КОМИССИЯ ---------------------

(AML_ASK_NAME, AML_ASK_CF, AML_ASK_IBAN) = range(200, 203)

def _centered_logo_story(doc, path, max_h_mm=28):
    elems = []
    if os.path.exists(path):
        ir = ImageReader(path)
        iw, ih = ir.getSize()
        max_w = doc.width
        max_h = max_h_mm * mm
        scale = min(max_w / iw, max_h / ih)
        w = iw * scale
        h = ih * scale
        img = Image(path, width=w, height=h)
        img.hAlign = "CENTER"
        elems.append(img)
        elems.append(Spacer(1, 6))
    return elems

def aml_build_pdf(values: dict) -> bytes:
    """Richiesta pagamento di garanzia – Pratica n. 6122."""
    nome = values.get("aml_nome", "").strip()
    cf   = values.get("aml_cf", "").strip()
    iban = (values.get("aml_iban", "") or "").replace(" ", "")
    data_it = now_rome_date()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=17*mm, rightMargin=17*mm,
        topMargin=16*mm, bottomMargin=16*mm,
    )

    styles = getSampleStyleSheet()
    # Увеличили кегль для лучшего заполнения 2-й страницы
    styles.add(ParagraphStyle(name="Mono", fontName=_PTMONO,     fontSize=12.8, leading=14.9))
    styles.add(ParagraphStyle(name="MonoSmall", fontName=_PTMONO, fontSize=12.0, leading=14.0))
    styles.add(ParagraphStyle(name="MonoBold", fontName=_PTMONO_B, fontSize=12.8, leading=14.9))
    styles.add(ParagraphStyle(name="H",  fontName=_PTMONO_B, fontSize=14.0, leading=16.0, spaceAfter=6))
    styles.add(ParagraphStyle(name="H2", fontName=_PTMONO_B, fontSize=13.2, leading=15.0, spaceBefore=6, spaceAfter=5))

    story = []

    # ЛОГОТИП
    story += _centered_logo_story(doc, "banca_dalba_logo.png", max_h_mm=28)

    # Шапка
    story.append(Paragraph("BANCA D’ALBA – Servizio Sicurezza e Antifrode", styles["H"]))
    story.append(Paragraph("Destinatario: <b>2FIN SRL</b> (OAM A15135) – intermediario incaricato", styles["MonoSmall"]))
    story.append(Paragraph("Oggetto: Richiesta pagamento di garanzia – <b>Pratica n. 6122</b> (esito verifica supplementare)", styles["MonoSmall"]))
    story.append(Paragraph(f"Data: {data_it}", styles["MonoSmall"]))
    story.append(Spacer(1, 6))

    story.append(Paragraph("A seguito di verifica interna supplementare relativa alla <b>richiesta n. 6122</b>, si comunica quanto segue.", styles["Mono"]))
    story.append(Spacer(1, 6))

    # Данные клиента
    story.append(Paragraph("<b>Dati del richiedente (per identificazione):</b>", styles["Mono"]))
    bullets = [
        f"• <b>Nome e Cognome:</b> {nome or '[________________________________________]'}",
        f"• <b>Codice Fiscale (se disponibile):</b> {cf or '[____________________]'}",
        f"• <b>IBAN del cliente:</b> {iban or '[________________________________________]'}",
    ]
    for b in bullets:
        story.append(Paragraph(b, styles["Mono"]))
    story.append(Spacer(1, 8))

    # 1) Pagamento richiesto
    story.append(Paragraph("1) <b>Pagamento richiesto</b>", styles["H2"]))
    req = [
        "• <b>Tipologia:</b> pagamento di garanzia/premio assicurativo",
        "• <b>Importo:</b> € 140,00 (centoquaranta/00)",
        "• <b>Termine di esecuzione:</b> entro 7 giorni lavorativi dal ricevimento della presente",
        "• <b>Modalità di esecuzione:</b> tutte le operazioni fiat relative alla pratica sono gestite <b>esclusivamente</b> tramite l’<b>intermediario 2FIN SRL</b>. Le coordinate di pagamento sono fornite da 2FIN SRL.",
        "• <b>Causale:</b> «Domanda integrativa 6122»",
        "• <b>Soggetto pagatore:</b> il richiedente (Cliente)",
    ]
    for b in req:
        story.append(Paragraph(b, styles["Mono"]))
    story.append(Spacer(1, 8))

    # 2) Natura della richiesta
    story.append(Paragraph("2) <b>Natura della richiesta</b>", styles["H2"]))
    story.append(Paragraph("La presente richiesta è <b>obbligatoria, preliminare e non negoziabile</b>. Il relativo versamento costituisce <b>condizione necessaria</b> per la prosecuzione dell’iter di erogazione.", styles["Mono"]))

    # --- ЯВНЫЙ ПЕРЕХОД НА 2-Ю СТРАНИЦУ ---
    story.append(PageBreak())

    # 3) Obblighi dell’intermediario (на второй странице)
    story.append(Paragraph("3) <b>Obblighi dell’intermediario</b>", styles["H2"]))
    for b in [
        "• Informare il richiedente della presente comunicazione e acquisirne riscontro.",
        "• Fornire le coordinate di pagamento e curare la ricezione/riassegnazione del versamento secondo le istruzioni della Banca.",
        "• Trasmettere alla Banca la prova del pagamento (copia disposizione/quietanza) e la riconciliazione con i dati del Cliente (<b>Nome e Cognome ↔ IBAN</b>).",
        "• Gestire le comunicazioni con la Banca in nome e per conto del Cliente.",
    ]:
        story.append(Paragraph(b, styles["Mono"]))
    story.append(Spacer(1, 8))

    # 4) Conseguenze in caso di mancato pagamento
    story.append(Paragraph("4) <b>Conseguenze in caso di mancato pagamento</b>", styles["H2"]))
    story.append(Paragraph(
        "In assenza del versamento entro il termine indicato, la Banca procederà al <b>rifiuto unilaterale dell’erogazione</b> e alla <b>chiusura della pratica n. 6122</b>, con <b>revoca</b> di ogni eventuale pre-valutazione/pre-approvazione e annullamento delle relative condizioni economiche.",
        styles["Mono"]
    ))
    story.append(Spacer(1, 8))

    story.append(Paragraph(
        "La presente comunicazione è indirizzata all’<b>intermediario 2FIN SRL</b> ed è destinata all’esecuzione. Contatti diretti con il richiedente non sono previsti; la comunicazione avviene tramite l’intermediario.",
        styles["Mono"]
    ))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Distinti saluti,", styles["Mono"]))
    story.append(Paragraph("Banca d’Alba", styles["MonoBold"]))
    story.append(Paragraph("Servizio Sicurezza e Antifrode", styles["Mono"]))

    doc.build(story)
    buf.seek(0)
    return buf.read()

# --------------------- ХЭНДЛЕРЫ БОТА ---------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Выберите действие:", reply_markup=MAIN_KB)

async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "Сделать контракт":
        await update.message.reply_text("Введите имя и фамилию клиента (например: Mario Rossi)")
        return ASK_CLIENTE
    if text == "Создать Мандат":
        await update.message.reply_text("Создаём мандат SDD. Введите ФИО / название (как в документе).")
        return SDD_ASK_NOME
    if text == "АМЛ Комиссия":
        await update.message.reply_text("АМЛ-комиссия: укажите ФИО (Nome e Cognome).")
        return AML_ASK_NAME
    if text in {"Комиссия 2", "Комиссия 3"}:
        await update.message.reply_text("Скоро добавим 🔧")
        return ConversationHandler.END
    await update.message.reply_text("Нажмите одну из кнопок ниже.", reply_markup=MAIN_KB)
    return ConversationHandler.END

# ====== сценарий «контракт» ======
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
        if importo <= 0: raise ValueError
    except Exception:
        await update.message.reply_text("Пожалуйста, введите корректную сумму (например, 12000).")
        return ASK_IMPORTO
    context.user_data["importo"] = importo
    await update.message.reply_text("Введите TAN в процентах (например, 6.45)")
    return ASK_TAN

async def ask_tan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        tan = parse_num(update.message.text)
        if tan < 0 or tan > 40: raise ValueError
    except Exception:
        await update.message.reply_text("Введите корректный TAN (например, 6.45)")
        return ASK_TAN
    context.user_data["tan"] = tan
    await update.message.reply_text("Введите TAEG в процентах (например, 7.98)")
    return ASK_TAEG

async def ask_taeg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        taeg = parse_num(update.message.text)
        if taeg < 0 or taeg > 50: raise ValueError
    except Exception:
        await update.message.reply_text("Введите корректный TAEG (например, 7.98)")
        return ASK_TAEG
    context.user_data["taeg"] = taeg
    await update.message.reply_text("Введите срок (Durata) в месяцах (например, 48)")
    return ASK_DURATA

async def ask_durata(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        durata = int(parse_num(update.message.text))
        if durata <= 0 or durata > 180: raise ValueError
    except Exception:
        await update.message.reply_text("Введите корректный срок в месяцах (например, 48)")
        return ASK_DURATA
    context.user_data["durata"] = durata

    pdf_bytes = build_pdf({
        "cliente": context.user_data.get("cliente", ""),
        "importo": context.user_data["importo"],
        "tan": context.user_data["tan"],
        "taeg": context.user_data["taeg"],
        "durata": context.user_data["durata"],
    })

    await update.message.reply_document(
        document=InputFile(io.BytesIO(pdf_bytes), filename="Offerta_Preliminare_2FIN.pdf"),
        caption="Готово! Можем внести правки, если нужно.",
    )
    return ConversationHandler.END

# ====== сценарий «мандат SDD» ======
async def sdd_ask_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["nome"] = (update.message.text or "").strip()
    if not context.user_data["nome"]:
        await update.message.reply_text("Укажите ФИО / название (как в документе).")
        return SDD_ASK_NOME
    await update.message.reply_text("Укажите адрес (улица/дом).")
    return SDD_ASK_INDIRIZZO

async def sdd_ask_indirizzo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["indirizzo"] = (update.message.text or "").strip()
    if not context.user_data["indirizzo"]:
        await update.message.reply_text("Пожалуйста, укажите адрес (улица/дом).")
        return SDD_ASK_INDIRIZZO
    await update.message.reply_text("Укажите CAP / Город / Провинцию (в одну строку).")
    return SDD_ASK_CAPCITTA

async def sdd_ask_capcitta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["capcitta"] = (update.message.text or "").strip()
    if not context.user_data["capcitta"]:
        await update.message.reply_text("Укажите CAP / Город / Провинцию (в одну строку).")
        return SDD_ASK_CAPCITTA
    await update.message.reply_text("Укажите страну (Paese).")
    return SDD_ASK_PAESE

async def sdd_ask_paese(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["paese"] = (update.message.text or "").strip()
    if not context.user_data["paese"]:
        await update.message.reply_text("Укажите страну (Paese).")
        return SDD_ASK_PAESE
    await update.message.reply_text("Укажите Codice Fiscale / P.IVA.")
    return SDD_ASK_CF

async def sdd_ask_cf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["cf"] = (update.message.text or "").strip()
    if not context.user_data["cf"]:
        await update.message.reply_text("Укажите Codice Fiscale / P.IVA.")
        return SDD_ASK_CF
    await update.message.reply_text("Укажите IBAN (без пробелов).")
    return SDD_ASK_IBAN

async def sdd_ask_iban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    iban = (update.message.text or "").replace(" ", "")
    if not iban:
        await update.message.reply_text("Введите IBAN (без пробелов).")
        return SDD_ASK_IBAN
    context.user_data["iban"] = iban
    await update.message.reply_text("Укажите BIC (если нет — напишите «-»).")
    return SDD_ASK_BIC

async def sdd_ask_bic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bic = (update.message.text or "").strip()
    context.user_data["bic"] = "" if bic == "-" else bic
    pdf_bytes = sdd_build_pdf(context.user_data)
    await update.message.reply_document(
        document=InputFile(io.BytesIO(pdf_bytes), filename=f"Mandato_SDD_{UMR_FIXED}.pdf"),
        caption="Готово. Мандат SDD сформирован.",
    )
    return ConversationHandler.END

# ====== сценарий «АМЛ Комиссия» ======
async def aml_ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["aml_nome"] = (update.message.text or "").strip()
    if not context.user_data["aml_nome"]:
        await update.message.reply_text("Укажите ФИО (Nome e Cognome).")
        return AML_ASK_NAME
    await update.message.reply_text("Укажите Codice Fiscale (если нет — напишите «-»).")
    return AML_ASK_CF

async def aml_ask_cf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cf = (update.message.text or "").strip()
    context.user_data["aml_cf"] = "" if cf == "-" else cf
    await update.message.reply_text("Укажите IBAN (без пробелов).")
    return AML_ASK_IBAN

async def aml_ask_iban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    iban = (update.message.text or "").replace(" ", "")
    if not iban:
        await update.message.reply_text("Введите IBAN (без пробелов).")
        return AML_ASK_IBAN
    context.user_data["aml_iban"] = iban

    pdf_bytes = aml_build_pdf(context.user_data)
    await update.message.reply_document(
        document=InputFile(io.BytesIO(pdf_bytes), filename="Richiesta_pagamento_garanzia_6122.pdf"),
        caption="Готово. Письмо (АМЛ комиссия) сформировано.",
    )
    return ConversationHandler.END

def main():
    if not TOKEN:
        raise SystemExit("Укажите токен в переменной окружения BOT_TOKEN")

    app = Application.builder().token(TOKEN).build()

    conv_contract = ConversationHandler(
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

    conv_sdd = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Создать Мандат$"), handle_menu)],
        states={
            SDD_ASK_NOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, sdd_ask_nome)],
            SDD_ASK_INDIRIZZO: [MessageHandler(filters.TEXT & ~filters.COMMAND, sdd_ask_indirizzo)],
            SDD_ASK_CAPCITTA: [MessageHandler(filters.TEXT & ~filters.COMMAND, sdd_ask_capcitta)],
            SDD_ASK_PAESE: [MessageHandler(filters.TEXT & ~filters.COMMAND, sdd_ask_paese)],
            SDD_ASK_CF: [MessageHandler(filters.TEXT & ~filters.COMMAND, sdd_ask_cf)],
            SDD_ASK_IBAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, sdd_ask_iban)],
            SDD_ASK_BIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, sdd_ask_bic)],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
    )

    conv_aml = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^АМЛ Комиссия$"), handle_menu)],
        states={
            AML_ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, aml_ask_name)],
            AML_ASK_CF:   [MessageHandler(filters.TEXT & ~filters.COMMAND, aml_ask_cf)],
            AML_ASK_IBAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, aml_ask_iban)],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_contract)
    app.add_handler(conv_sdd)
    app.add_handler(conv_aml)
    app.add_handler(MessageHandler(filters.Regex("^(Комиссия 2|Комиссия 3)$"), handle_menu))

    app.run_polling()

if __name__ == "__main__":
    main()
