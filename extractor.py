"""Ekstraksi data Kartu Keluarga menggunakan Tesseract OCR lokal.

Fungsi publik extract(path) mempertahankan kontrak versi sebelumnya:
return (hasil_dict, pesan_peringatan_atau_None).
OCR bersifat best-effort; pengguna tetap harus memeriksa halaman konfirmasi.
"""

import os
import re
from collections import defaultdict

from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import pytesseract
from pytesseract import Output

from schema import KK_FIELDS, ANGGOTA_FIELDS

# Jika Tesseract tidak terdeteksi otomatis (umum di Windows), atur
# TESSERACT_CMD di environment/.env ke lokasi tesseract.exe.
_tesseract_cmd = os.getenv("TESSERACT_CMD")
if _tesseract_cmd:
    pytesseract.pytesseract.tesseract_cmd = _tesseract_cmd

OCR_LANG = os.getenv("TESSERACT_LANG", "ind+eng")


def empty_result():
    return {
        "kk": {field: "" for field, _ in KK_FIELDS},
        "anggota": [],
    }


def _clean(value):
    value = re.sub(r"\s+", " ", str(value or "")).strip(" :;|\t\n")
    return "" if value in {"-", ".", "—", "–"} else value


def _preprocess(image):
    """Persiapkan scan/foto tanpa mengubah isi dokumen."""
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((2800, 2800))
    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    gray = ImageEnhance.Contrast(gray).enhance(1.6)
    return gray.filter(ImageFilter.SHARPEN)


def _orient(image):
    """Gunakan OSD Tesseract; fallback memilih rotasi dengan teks terbanyak."""
    try:
        osd = pytesseract.image_to_osd(image, lang="osd")
        match = re.search(r"Rotate:\s*(\d+)", osd)
        if match:
            degrees = int(match.group(1)) % 360
            if degrees:
                image = image.rotate(degrees, expand=True)
        return image
    except pytesseract.TesseractError:
        pass
    except Exception:
        pass

    # OSD terkadang gagal pada scan yang berisi tabel. Uji empat orientasi.
    candidates = []
    for degrees in (0, 90, 180, 270):
        candidate = image.rotate(degrees, expand=True) if degrees else image
        try:
            sample = pytesseract.image_to_string(candidate, lang=OCR_LANG, config="--psm 6")
            score = len(re.findall(r"[A-Za-z0-9]{2,}", sample))
        except Exception:
            score = -1
        candidates.append((score, candidate))
    return max(candidates, key=lambda item: item[0])[1]


def _ocr_lines(image):
    """Ambil baris OCR beserta posisi kata untuk mengenali baris anggota."""
    data = pytesseract.image_to_data(
        image,
        lang=OCR_LANG,
        config="--oem 3 --psm 6",
        output_type=Output.DICT,
    )
    grouped = defaultdict(list)
    for i, raw in enumerate(data.get("text", [])):
        word = _clean(raw)
        if not word:
            continue
        try:
            confidence = float(data["conf"][i])
        except (ValueError, TypeError, KeyError):
            confidence = -1
        if confidence < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        grouped[key].append({
            "text": word,
            "left": int(data["left"][i]),
            "top": int(data["top"][i]),
            "confidence": confidence,
        })

    lines = []
    for words in grouped.values():
        words.sort(key=lambda word: word["left"])
        lines.append({
            "text": " ".join(word["text"] for word in words),
            "words": words,
            "top": min(word["top"] for word in words),
        })
    return sorted(lines, key=lambda line: line["top"])


def _all_text(lines):
    return "\n".join(line["text"] for line in lines)


def _find_value(text, labels, stop_labels=()):
    """Cari nilai setelah label dan hentikan sebelum label kolom berikutnya."""
    lines = text.splitlines()
    all_stops = sorted(set(tuple(stop_labels) + (
        "Nama Kepala Keluarga", "Alamat", "RT/RW", "RT RW", "Kode Pos",
        "Desa/Kelurahan", "Kecamatan", "Kabupaten/Kota", "Provinsi",
        "Dikeluarkan Tanggal",
    )), key=len, reverse=True)
    for line in lines:
        for label in sorted(labels, key=len, reverse=True):
            match = re.search(re.escape(label) + r"\s*[:.]?\s*(.*)$", line, re.I)
            if not match:
                continue
            value = match.group(1)
            for stop in all_stops:
                if stop.lower() == label.lower():
                    continue
                value = re.split(re.escape(stop), value, maxsplit=1, flags=re.I)[0]
            value = re.sub(r"^\s*\d{1,2}\s+", "", value)
            value = _clean(value)
            if value:
                return value
    return ""


def _parse_identity(text):
    result = empty_result()["kk"]

    # Nomor KK merupakan deretan 16 digit; jangan mengubahnya menjadi integer.
    compact = re.sub(r"(?<!\d)(?:\d[ .-]*){16}(?!\d)", lambda m: re.sub(r"\D", "", m.group()), text)
    nik_candidates = re.findall(r"(?<!\d)\d{16}(?!\d)", compact)
    if nik_candidates:
        result["no_kk"] = nik_candidates[0]

    labels = {
        "nama_kepala_keluarga": ["Nama Kepala Keluarga", "Kepala Keluarga"],
        "alamat": ["Alamat"],
        "rt_rw": ["RT/RW", "RT RW"],
        "kode_pos": ["Kode Pos"],
        "desa_kelurahan": ["Desa/Kelurahan", "Kelurahan", "Desa"],
        "kecamatan": ["Kecamatan"],
        "kabupaten_kota": ["Kabupaten/Kota", "Kabupaten", "Kota"],
        "provinsi": ["Provinsi"],
        "tanggal_dikeluarkan": ["Dikeluarkan Tanggal", "Dikeluarkan"],
    }
    for field, aliases in labels.items():
        result[field] = _find_value(text, aliases)

    issued = re.search(r"Dikeluarkan\s+Tanggal\s*[:.]?\s*(\d{2}[-/.]\d{2}[-/.]\d{4})", text, re.I)
    if issued:
        result["tanggal_dikeluarkan"] = issued.group(1).replace("/", "-").replace(".", "-")
    result["nama_kepala_keluarga"] = result["nama_kepala_keluarga"].rstrip(" .,:;")
    result["provinsi"] = result["provinsi"].rstrip(" .,:;")

    # Pola RT/RW dan kode pos juga sering terbaca tanpa label yang utuh.
    if not result["rt_rw"]:
        match = re.search(r"RT\s*[/.-]?\s*RW[^0-9]{0,5}(\d{3}\s*[/.-]\s*\d{3})", text, re.I)
        if match:
            result["rt_rw"] = re.sub(r"\s+", "", match.group(1)).replace("-", "/").replace(".", "/")
    if not result["kode_pos"]:
        match = re.search(r"\b\d{5}\b", text)
        if match:
            result["kode_pos"] = match.group(0)
    return result


def _parse_members(lines, no_kk=""):
    """Ambil pasangan nama/NIK yang benar-benar terbaca pada baris tabel.

    Karena scan tabel KK sering membuat OCR menggabungkan kolom, parser tidak
    menebak NIK yang tidak terbaca utuh. Kolom lain disediakan untuk koreksi manual.
    """
    members = []
    seen = set()
    for line in lines:
        line_text = line["text"]
        compact = re.sub(r"(?<=\d)\s+(?=\d)", "", line_text)
        match = re.search(r"(?<![0-9A-Za-z])([0-9nN]{16})(?![0-9A-Za-z])", compact)
        if not match:
            continue
        nik = match.group(1).replace("n", "1").replace("N", "1")
        if nik == no_kk or nik in seen:
            continue

        before = _clean(compact[:match.start()])
        before = re.sub(r"^\s*\d{1,2}\s*[.)|\]-]?\s*", "", before)
        before = re.sub(r"^[^A-Za-zÀ-ÿ]+", "", before)
        if not re.search(r"[A-Za-zÀ-ÿ]{2,}", before):
            continue

        member = {field: "" for field, _ in ANGGOTA_FIELDS}
        member["nama_lengkap"] = before
        member["nik"] = nik
        members.append(member)
        seen.add(nik)
    return members or [{field: "" for field, _ in ANGGOTA_FIELDS}]


def _normalize_language_error(error):
    message = str(error)
    if "Failed loading language" in message or "Error opening data file" in message:
        return (
            "Data bahasa Tesseract belum tersedia. Pasang traineddata bahasa Indonesia "
            "(ind) atau ubah TESSERACT_LANG=eng."
        )
    if "tesseract is not installed" in message.lower() or "not in your path" in message.lower():
        return "Tesseract belum terpasang atau belum masuk PATH. Ikuti petunjuk instalasi di README.md."
    return f"OCR gagal ({message}). Silakan periksa instalasi Tesseract atau isi form secara manual."


def extract(path):
    """Return (hasil, pesan_peringatan_atau_None). Tidak pernah raise."""
    result = empty_result()
    try:
        with Image.open(path) as source:
            image = _preprocess(source)
        image = _orient(image)
        lines = _ocr_lines(image)
        text = _all_text(lines)
        result["kk"] = _parse_identity(text)
        result["anggota"] = _parse_members(lines, result["kk"].get("no_kk", ""))

        if not result["kk"].get("no_kk") and not result["anggota"]:
            return result, "Teks belum berhasil dikenali dengan baik. Periksa instalasi bahasa Tesseract atau isi form secara manual."
        return result, "Hasil OCR masih perlu diperiksa. Pastikan nomor KK, NIK, nama, dan tanggal sudah benar."
    except Exception as error:
        return result, _normalize_language_error(error)
