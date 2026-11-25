# KK Reader — Flask + Tesseract OCR

Aplikasi web mini untuk mengunggah gambar Kartu Keluarga (KK), membaca teks secara lokal menggunakan Tesseract OCR, mengoreksi hasil pembacaan, lalu menyimpannya ke SQLite. Data KK dapat dicari, dilihat, diubah, dan dihapus.

**Stack:** Python 3.10+, Flask, SQLite, Pillow, pytesseract, Tesseract OCR.

> Gunakan dokumen dummy untuk demo. KK berisi data pribadi; jangan unggah atau commit KK asli.

## 1. Instalasi Tesseract OCR

`pytesseract` adalah wrapper Python. Program Tesseract tetap harus dipasang secara terpisah.

### Windows

1. Instal Tesseract OCR untuk Windows (misalnya distribusi UB Mannheim): https://github.com/UB-Mannheim/tesseract/wiki
2. Saat instalasi, pastikan bahasa **Indonesian (ind)** tersedia. Jika tidak, unduh `ind.traineddata` dari https://github.com/tesseract-ocr/tessdata dan letakkan di folder `tessdata` instalasi Tesseract.
3. Pastikan `tesseract.exe` masuk ke PATH. Jika tidak, atur `TESSERACT_CMD` pada file `.env` ke lokasi `tesseract.exe`.

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install tesseract-ocr tesseract-ocr-ind tesseract-ocr-eng
```

Verifikasi instalasi:

```bash
tesseract --version
tesseract --list-langs
```

Pastikan daftar bahasa memuat `ind` dan `eng`.

## 2. Menjalankan aplikasi

```bash
git clone <url-repo-ini>
cd kk-app
python -m venv .venv
```

Aktifkan virtual environment:

```bash
# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

Pasang dependency dan siapkan konfigurasi:

```bash
pip install -r requirements.txt
copy .env.example .env       # Windows
# cp .env.example .env       # macOS / Linux
python app.py
```

Buka http://127.0.0.1:5000.

Jika Tesseract tidak ditemukan, isi `TESSERACT_CMD` pada `.env`. Contoh Windows:

```env
TESSERACT_CMD=C:\\Program Files\\Tesseract-OCR\\tesseract.exe
TESSERACT_LANG=ind+eng
```

## 3. Alur aplikasi

1. `/` — unggah gambar KK (PNG/JPG/WEBP).
2. `/upload` — gambar diproses dengan Tesseract OCR lokal.
3. Halaman konfirmasi — pengguna memeriksa dan mengoreksi identitas KK serta anggota keluarga.
4. `/save` — data yang sudah dikonfirmasi disimpan ke SQLite.
5. `/kk` — pencarian/daftar KK.
6. `/kk/<id>` — detail KK dan daftar anggota; tersedia tambah, edit, dan hapus anggota.
7. `/kk/<id>/edit` — edit identitas KK.

Menghapus KK juga menghapus anggota terkait melalui foreign key `ON DELETE CASCADE`.

## 4. Struktur database

Database `kk.db` dibuat otomatis saat aplikasi dijalankan.

- `tbl_identitasKK`: nomor KK, kepala keluarga, alamat, RT/RW, kode pos, desa/kelurahan, kecamatan, kabupaten/kota, provinsi, tanggal dikeluarkan, dan nama file gambar.
- `tbl_anggotaKeluargaKK`: relasi KK, nomor urut, nama, NIK, jenis kelamin, tempat/tanggal lahir, agama, pendidikan, pekerjaan, golongan darah, status perkawinan, tanggal perkawinan, status hubungan, kewarganegaraan, paspor, KITAP, nama ayah, dan nama ibu.

Daftar field untuk form dan database berada di `schema.py`.

## 5. Catatan akurasi OCR

- OCR berjalan lokal; aplikasi tidak membutuhkan API key atau koneksi ke layanan OCR eksternal.
- Orientasi gambar dicoba menggunakan Tesseract OSD, dengan fallback pengujian empat rotasi.
- Parser saat ini mencoba mengambil nomor KK dan pasangan nama/NIK yang terbaca jelas. Kolom tabel lain dapat perlu diisi atau diperbaiki manual.
- Struktur tabel pada scan/foto bisa membuat urutan teks OCR berubah. Selalu cocokkan hasil dengan gambar asli, terutama NIK dan tanggal lahir.
- Hasil OCR bukan verifikasi identitas atau dokumen resmi.

## 6. Struktur proyek

```text
app.py         route Flask + akses database
extractor.py   preprocessing, Tesseract OCR, dan parsing dasar
schema.py      definisi field KK dan anggota
requirements.txt
.env.example
templates/     halaman HTML (Jinja)
static/        CSS
uploads/       gambar yang diunggah (tidak ikut git)
```

## 7. Keamanan dan GitHub

File `.env`, database lokal `kk.db`, virtual environment, dan isi folder `uploads/` diabaikan oleh Git. Jangan commit data KK asli atau rahasia konfigurasi.
