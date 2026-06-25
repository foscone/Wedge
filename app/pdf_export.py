"""Generazione del PDF di stampa: planimetria con i coni ottici delle foto
selezionate + le foto stesse, raggruppate per planimetria.

La geometria dei coni replica esattamente quella del canvas frontend
(app/static/app.js): x,y in pixel ORIGINALI della planimetria (origine in
alto a sinistra, y verso il basso), angolo in gradi con atan2(dy,dx) in
spazio schermo, lunghezza del cono = 12% del lato maggiore della planimetria.
La planimetria può essere declassata (downscale) per tenere il PDF leggero,
ma la mappatura dei coni usa SEMPRE le dimensioni originali, altrimenti i
coni finiscono fuori posto.
"""

import io
import math
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps
from reportlab.lib.pagesizes import A3, A4, landscape, portrait
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdfcanvas

PAGE_SIZES = {"A4": A4, "A3": A3}

MARGIN = 1.2 * cm              # margini laterali del contenuto
EDGE = 0.55 * cm              # distanza intestazione/piè dal bordo
GUTTER = 0.4 * cm             # spazio tra le foto
CAPTION_H = 0.15 * cm         # piccolo respiro sotto ogni riga di foto
MAX_PHOTO_H = 7 * cm          # altezza massima di una foto (foto più piccole = più file)
CONE_FRAC = 0.12              # lunghezza cono = 12% del lato maggiore (come il frontend)
PLAN_MAX_HEIGHT_FRAC = 0.55   # quota massima dell'area contenuto per la planimetria
MAX_IMG_PX = 1800            # downscale delle immagini per tenere il PDF leggero

# Colori coni (coerenti con il frontend, versione non-evidenziata)
COL_PHOTO = (76 / 255, 200 / 255, 140 / 255)   # verde
COL_VIDEO = (220 / 255, 150 / 255, 60 / 255)   # arancio
COL_BADGE = (0.16, 0.42, 1.0)                  # blu del numero

HEAD_FONT = ("Helvetica", 9)
LINE_H = 12


def _load_image(path: Path, downscale: bool = True) -> Optional[Image.Image]:
    try:
        im = Image.open(path)
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
        if downscale and max(im.size) > MAX_IMG_PX:
            im.thumbnail((MAX_IMG_PX, MAX_IMG_PX))
        return im
    except Exception:
        return None


def _load_plan(path: Path):
    """Ritorna (immagine_per_embed, larghezza_orig, altezza_orig) oppure
    (None, 0, 0). Le dimensioni originali servono per posizionare i coni."""
    try:
        im = Image.open(path)
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
        ow, oh = im.size
        if max(im.size) > MAX_IMG_PX:
            im = im.copy()
            im.thumbnail((MAX_IMG_PX, MAX_IMG_PX))
        return im, ow, oh
    except Exception:
        return None, 0, 0


class _Builder:
    def __init__(self, page_size, header_text: str, footer_text: str):
        self.W, self.H = page_size
        self.header_lines = [l for l in (header_text or "").splitlines() if l.strip()]
        self.footer_lines = [l for l in (footer_text or "").splitlines() if l.strip()]
        self.buf = io.BytesIO()
        self.c = pdfcanvas.Canvas(self.buf, pagesize=page_size)

        nh, nf = len(self.header_lines), len(self.footer_lines)
        # blocco intestazione: testo (vicino al bordo) + riga separatrice sotto
        self._head_sep_y = self.H - EDGE - nh * LINE_H - 3 if nh else None
        self._foot_sep_y = EDGE + nf * LINE_H + 3 if nf else None

        self.content_x0 = MARGIN
        self.content_w = self.W - 2 * MARGIN
        self.content_top = (self._head_sep_y - 6) if nh else (self.H - EDGE)
        self.content_bottom = (self._foot_sep_y + 6) if nf else (EDGE)
        self.content_h = self.content_top - self.content_bottom

        self.y = None
        self._started = False
        self._row = []
        self._ncols = 2
        self._cell_w = self.content_w
        self._max_h = MAX_PHOTO_H

    # -- intestazione / piè di pagina (compatti, riga solo sotto al testo) --
    def _draw_header_footer(self):
        c = self.c
        c.setFont(*HEAD_FONT)
        c.setFillGray(0.25)
        c.setStrokeGray(0.65)
        c.setLineWidth(0.5)
        if self.header_lines:
            y = self.H - EDGE - 9
            maxw = 0.0
            for line in self.header_lines:
                c.drawCentredString(self.W / 2, y, line)
                maxw = max(maxw, c.stringWidth(line, *HEAD_FONT))
                y -= LINE_H
            half = maxw / 2 + 8
            c.line(self.W / 2 - half, self._head_sep_y, self.W / 2 + half, self._head_sep_y)
        if self.footer_lines:
            n = len(self.footer_lines)
            y = EDGE + (n - 1) * LINE_H
            maxw = 0.0
            for line in self.footer_lines:
                c.drawCentredString(self.W / 2, y, line)
                maxw = max(maxw, c.stringWidth(line, *HEAD_FONT))
                y -= LINE_H
            half = maxw / 2 + 8
            c.line(self.W / 2 - half, self._foot_sep_y, self.W / 2 + half, self._foot_sep_y)

    def new_page(self):
        if self._started:
            self.c.showPage()
        self._draw_header_footer()
        self.y = self.content_top
        self._started = True

    # -- planimetria + coni ------------------------------------------------
    def draw_plan(self, plan_img: Image.Image, ow: int, oh: int, medias: list[dict]):
        max_w = self.content_w
        max_h = self.content_h * PLAN_MAX_HEIGHT_FRAC
        s = min(max_w / ow, max_h / oh)
        draw_w, draw_h = ow * s, oh * s
        x0 = self.content_x0 + (self.content_w - draw_w) / 2
        y0 = self.y - draw_h
        self.c.drawImage(ImageReader(plan_img), x0, y0, draw_w, draw_h)

        # px,py in pixel ORIGINALI della planimetria -> coordinate PDF
        def to_pdf(px, py):
            return (x0 + px * s, y0 + (oh - py) * s)

        cone_len = max(ow, oh) * CONE_FRAC
        for m in medias:
            self._draw_cone(to_pdf, m, cone_len)
        self.y = y0 - 0.5 * cm

    def _draw_cone(self, to_pdf, m: dict, length_px: float):
        if m.get("x") is None or m.get("y") is None or m.get("angle") is None:
            return
        x, y = float(m["x"]), float(m["y"])
        angle = float(m["angle"])
        fov = float(m.get("fov") or 60)
        a = math.radians(angle)
        half = math.radians(fov / 2)
        steps = 28
        pts = [to_pdf(x, y)]
        for k in range(steps + 1):
            t = a - half + (2 * half) * k / steps
            pts.append(to_pdf(x + length_px * math.cos(t), y + length_px * math.sin(t)))

        video = m.get("kind") == "video"
        col = COL_VIDEO if video else COL_PHOTO
        c = self.c
        c.saveState()
        path = c.beginPath()
        path.moveTo(*pts[0])
        for p in pts[1:]:
            path.lineTo(*p)
        path.close()
        c.setFillColorRGB(*col)
        c.setStrokeColorRGB(*col)
        c.setFillAlpha(0.35)
        c.setStrokeAlpha(0.9)
        c.setLineWidth(1.2)
        c.drawPath(path, fill=1, stroke=1)
        c.restoreState()

        ax, ay = pts[0]
        self._badge(ax, ay, m["_num"])

    def _badge(self, cx, cy, number: int):
        c = self.c
        r = 7
        c.saveState()
        c.setFillColorRGB(*COL_BADGE)
        c.setStrokeColorRGB(1, 1, 1)
        c.setLineWidth(1)
        c.circle(cx, cy, r, fill=1, stroke=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(cx, cy - 3, str(number))
        c.restoreState()

    # -- foto in righe ad altezza uniforme, impaccate (poco bianco) --------
    def setup_grid(self):
        # altezza uniforme delle foto: così le verticali non lasciano bianco
        # ai lati e ci stanno almeno due file di foto per pagina.
        self._target_h = min(MAX_PHOTO_H, (self.content_h - 2 * CAPTION_H - GUTTER) / 2)
        self._row = []
        self._row_w = 0.0

    def add_photo(self, img: Image.Image, number: int):
        iw, ih = img.size
        aspect = iw / ih if ih else 1.0
        h = self._target_h
        w = h * aspect
        if w > self.content_w:  # foto molto panoramica: sta su tutta la riga
            w = self.content_w
            h = w / aspect
        if self._row and self._row_w + GUTTER + w > self.content_w + 0.5:
            self.flush_row()
        self._row.append((img, w, h, number))
        self._row_w += (GUTTER if self._row else 0) + w

    def flush_row(self):
        if not self._row:
            return
        row_h = max(h for _, _, h, _ in self._row)
        need = row_h + CAPTION_H
        if self.y is None or self.y - need < self.content_bottom:
            self.new_page()
        top = self.y
        x = self.content_x0
        for img, w, h, number in self._row:
            iy = top - h
            self.c.drawImage(ImageReader(img), x, iy, w, h)
            self.c.setStrokeGray(0.6)
            self.c.setLineWidth(0.5)
            self.c.rect(x, iy, w, h, fill=0, stroke=1)
            self._badge(x + 11, top - 11, number)
            x += w + GUTTER
        self.y = top - need - GUTTER * 0.5
        self._row = []
        self._row_w = 0.0

    def output(self) -> bytes:
        if self._started:
            self.c.showPage()
        self.c.save()
        return self.buf.getvalue()


def build_pdf(
    *,
    groups: list[dict],
    page_size: str = "A4",
    orientation: str = "portrait",
    header_text: str = "",
    footer_text: str = "",
) -> bytes:
    """`groups`: lista ordinata di dict con:
        - "plan_path": Path | None  (immagine della planimetria, se presente)
        - "medias": lista di dict {name, x, y, angle, fov, kind, embed_path}
    Ogni gruppo inizia su una nuova pagina; la planimetria non viene ripetuta
    sulle pagine successive dello stesso gruppo.
    `orientation`: "portrait" (verticale) o "landscape" (orizzontale).
    """
    pg = PAGE_SIZES.get(page_size, A4)
    pg = landscape(pg) if orientation == "landscape" else portrait(pg)
    b = _Builder(pg, header_text, footer_text)

    for group in groups:
        medias = group["medias"]
        for i, m in enumerate(medias):
            m["_num"] = i + 1
        b.new_page()

        plan_path = group.get("plan_path")
        plan_img, ow, oh = _load_plan(plan_path) if plan_path else (None, 0, 0)
        if plan_img is not None:
            b.draw_plan(plan_img, ow, oh, medias)
        else:
            b.c.setFont("Helvetica-Oblique", 10)
            b.c.setFillGray(0.4)
            label = group.get("plan_name") or "Foto senza planimetria"
            b.c.drawString(b.content_x0, b.y - 12, label)
            b.y -= 0.9 * cm

        b.setup_grid()
        for m in medias:
            img = _load_image(m.get("embed_path")) if m.get("embed_path") else None
            if img is not None:
                b.add_photo(img, m["_num"])
        b.flush_row()

    return b.output()
