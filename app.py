import os, sqlite3, uuid
from dotenv import load_dotenv
load_dotenv()
from flask import (Flask, g, render_template, request, redirect, url_for,
                   flash, send_from_directory, abort)
from schema import KK_FIELDS, ANGGOTA_FIELDS
import extractor

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
DB_PATH = os.path.join(BASE, "kk.db")
ALLOWED = {".png", ".jpg", ".jpeg", ".webp"}

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-only-change-me")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

KK_COLS = [f for f, _ in KK_FIELDS]
AG_COLS = [f for f, _ in ANGGOTA_FIELDS]


# ---------- database ----------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()


def init_db():
    kk = ",\n".join(f"{c} TEXT" + (" NOT NULL UNIQUE" if c == "no_kk" else "") for c in KK_COLS)
    ag = ",\n".join(f"{c} TEXT" for c in AG_COLS)
    con = sqlite3.connect(DB_PATH)
    con.executescript(f"""
    CREATE TABLE IF NOT EXISTS tbl_identitasKK (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        {kk},
        image_file TEXT
    );
    CREATE TABLE IF NOT EXISTS tbl_anggotaKeluargaKK (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kk_id INTEGER NOT NULL REFERENCES tbl_identitasKK(id) ON DELETE CASCADE,
        no_urut INTEGER,
        {ag}
    );""")
    con.close()


def insert(table, data):
    cols = list(data)
    cur = db().execute(
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [data[c] for c in cols])
    return cur.lastrowid


def update(table, row_id, data):
    sets = ",".join(f"{c}=?" for c in data)
    db().execute(f"UPDATE {table} SET {sets} WHERE id=?", [*data.values(), row_id])


def get_kk(kk_id):
    row = db().execute("SELECT * FROM tbl_identitasKK WHERE id=?", (kk_id,)).fetchone()
    return row or abort(404)


def get_anggota(a_id):
    row = db().execute("SELECT * FROM tbl_anggotaKeluargaKK WHERE id=?", (a_id,)).fetchone()
    return row or abort(404)


def form_values(fields, prefix=""):
    return {f: request.form.get(prefix + f, "").strip() for f, _ in fields}


# ---------- upload & konfirmasi ----------
@app.get("/")
def upload_page():
    return render_template("upload.html")


@app.post("/upload")
def upload():
    file = request.files.get("image")
    ext = os.path.splitext(file.filename or "")[1].lower() if file else ""
    if not file or ext not in ALLOWED:
        flash("Pilih file gambar (PNG/JPG/WEBP).", "error")
        return redirect(url_for("upload_page"))
    name = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, name)
    file.save(path)
    result, warning = extractor.extract(path)
    if warning:
        flash(warning, "error")
    return render_template("confirm.html", kk=result["kk"], anggota=result["anggota"],
                           image_file=name)


@app.post("/save")
def save():
    kk = form_values(KK_FIELDS)
    image_file = os.path.basename(request.form.get("image_file", ""))
    n = len(request.form.getlist("a_nama_lengkap"))
    anggota = []
    for i in range(n):
        row = {f: request.form.getlist("a_" + f)[i].strip() for f in AG_COLS}
        if row["nama_lengkap"] or row["nik"]:
            anggota.append(row)

    def back(msg):
        flash(msg, "error")
        return render_template("confirm.html", kk=kk, anggota=anggota or [{}], image_file=image_file)

    if not kk["no_kk"]:
        return back("No. KK wajib diisi.")
    try:
        kk_id = insert("tbl_identitasKK", {**kk, "image_file": image_file})
        for i, row in enumerate(anggota, 1):
            insert("tbl_anggotaKeluargaKK", {"kk_id": kk_id, "no_urut": i, **row})
        db().commit()
    except sqlite3.IntegrityError:
        db().rollback()
        return back(f"No. KK {kk['no_kk']} sudah ada di database.")
    flash("Data KK berhasil disimpan.", "ok")
    return redirect(url_for("detail", kk_id=kk_id))


@app.get("/uploads/<path:name>")
def uploaded(name):
    return send_from_directory(UPLOAD_DIR, name)


# ---------- tabel KK ----------
@app.get("/kk")
def list_kk():
    q = request.args.get("q", "").strip()
    sql = """SELECT k.*, (SELECT COUNT(*) FROM tbl_anggotaKeluargaKK a WHERE a.kk_id=k.id) AS jml
             FROM tbl_identitasKK k"""
    args = []
    if q:
        sql += " WHERE no_kk LIKE ? OR nama_kepala_keluarga LIKE ? OR desa_kelurahan LIKE ?"
        args = [f"%{q}%"] * 3
    rows = db().execute(sql + " ORDER BY k.id DESC", args).fetchall()
    return render_template("list.html", rows=rows, q=q)


@app.get("/kk/<int:kk_id>")
def detail(kk_id):
    kk = get_kk(kk_id)
    anggota = db().execute(
        "SELECT * FROM tbl_anggotaKeluargaKK WHERE kk_id=? ORDER BY no_urut, id", (kk_id,)).fetchall()
    return render_template("detail.html", kk=kk, anggota=anggota, fields=KK_FIELDS)


@app.route("/kk/<int:kk_id>/edit", methods=["GET", "POST"])
def edit_kk(kk_id):
    kk = get_kk(kk_id)
    if request.method == "POST":
        data = form_values(KK_FIELDS)
        try:
            update("tbl_identitasKK", kk_id, data)
            db().commit()
        except sqlite3.IntegrityError:
            db().rollback()
            flash("No. KK sudah dipakai KK lain.", "error")
            return render_template("form.html", title="Edit Identitas KK", fields=KK_FIELDS,
                                   values=data, back=url_for("detail", kk_id=kk_id))
        flash("Identitas KK diperbarui.", "ok")
        return redirect(url_for("detail", kk_id=kk_id))
    return render_template("form.html", title="Edit Identitas KK", fields=KK_FIELDS,
                           values=kk, back=url_for("detail", kk_id=kk_id))


@app.post("/kk/<int:kk_id>/delete")
def delete_kk(kk_id):
    kk = get_kk(kk_id)
    db().execute("DELETE FROM tbl_identitasKK WHERE id=?", (kk_id,))  # anggota ikut terhapus (CASCADE)
    db().commit()
    if kk["image_file"]:
        try:
            os.remove(os.path.join(UPLOAD_DIR, os.path.basename(kk["image_file"])))
        except OSError:
            pass
    flash("KK beserta anggotanya dihapus.", "ok")
    return redirect(url_for("list_kk"))


# ---------- anggota ----------
@app.route("/kk/<int:kk_id>/anggota/new", methods=["GET", "POST"])
def new_anggota(kk_id):
    get_kk(kk_id)
    if request.method == "POST":
        data = form_values(ANGGOTA_FIELDS)
        nxt = db().execute("SELECT COALESCE(MAX(no_urut),0)+1 FROM tbl_anggotaKeluargaKK WHERE kk_id=?",
                           (kk_id,)).fetchone()[0]
        insert("tbl_anggotaKeluargaKK", {"kk_id": kk_id, "no_urut": nxt, **data})
        db().commit()
        flash("Anggota ditambahkan.", "ok")
        return redirect(url_for("detail", kk_id=kk_id))
    return render_template("form.html", title="Tambah Anggota", fields=ANGGOTA_FIELDS,
                           values={}, back=url_for("detail", kk_id=kk_id))


@app.route("/anggota/<int:a_id>/edit", methods=["GET", "POST"])
def edit_anggota(a_id):
    a = get_anggota(a_id)
    back = url_for("detail", kk_id=a["kk_id"])
    if request.method == "POST":
        update("tbl_anggotaKeluargaKK", a_id, form_values(ANGGOTA_FIELDS))
        db().commit()
        flash("Data anggota diperbarui.", "ok")
        return redirect(back)
    return render_template("form.html", title=f"Edit Anggota: {a['nama_lengkap']}",
                           fields=ANGGOTA_FIELDS, values=a, back=back)


@app.post("/anggota/<int:a_id>/delete")
def delete_anggota(a_id):
    a = get_anggota(a_id)
    db().execute("DELETE FROM tbl_anggotaKeluargaKK WHERE id=?", (a_id,))
    db().commit()
    flash("Anggota dihapus.", "ok")
    return redirect(url_for("detail", kk_id=a["kk_id"]))


@app.context_processor
def inject_fields():
    return {"kk_fields": KK_FIELDS, "anggota_fields": ANGGOTA_FIELDS}


init_db()

if __name__ == "__main__":
    app.run(debug=True)
