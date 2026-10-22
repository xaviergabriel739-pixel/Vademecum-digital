"""
Importa palavras-chave da planilha de expansão para o SQLite existente.
ANTES DE EXECUTAR:
1) Faça uma cópia de segurança do banco.
2) Confira DB_PATH.
3) Revise as associações na aba Importar_palavras.
4) Exporte a aba Importar_palavras como CSV UTF-8 chamado Importar_palavras.csv
   na mesma pasta deste script.
"""
import csv
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "vademecum.db"
CSV_PATH = BASE / "Importar_palavras.csv"

def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Banco não encontrado: {DB_PATH}")
    if not CSV_PATH.exists():
        raise FileNotFoundError(
            f"CSV não encontrado: {CSV_PATH}. Exporte a aba Importar_palavras como CSV UTF-8."
        )

    con = sqlite3.connect(DB_PATH)
    try:
        cur = con.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        inserted_keywords = 0
        inserted_links = 0

        with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            required = {"palavra_chave", "id_dispositivo"}
            if not required.issubset(reader.fieldnames or []):
                raise ValueError(f"CSV precisa das colunas: {sorted(required)}")

            cur.execute("BEGIN")
            for row in reader:
                word = (row.get("palavra_chave") or "").strip()
                device_id = (row.get("id_dispositivo") or "").strip()
                if not word or not device_id:
                    continue
                try:
                    device_id = int(device_id)
                except ValueError:
                    raise ValueError(f"id_dispositivo inválido: {device_id}")

                exists = cur.execute(
                    "SELECT 1 FROM dispositivos WHERE id = ?", (device_id,)
                ).fetchone()
                if not exists:
                    raise ValueError(f"Dispositivo {device_id} não existe no banco.")

                before = cur.execute(
                    "SELECT id FROM palavras_chave WHERE palavra = ?", (word,)
                ).fetchone()
                cur.execute(
                    "INSERT OR IGNORE INTO palavras_chave (palavra) VALUES (?)",
                    (word,)
                )
                if before is None:
                    inserted_keywords += 1

                keyword_id = cur.execute(
                    "SELECT id FROM palavras_chave WHERE palavra = ?", (word,)
                ).fetchone()[0]
                cur.execute("""
                    INSERT OR IGNORE INTO dispositivos_palavras_chave
                        (id_dispositivo, id_palavra_chave)
                    VALUES (?, ?)
                """, (device_id, keyword_id))
                inserted_links += cur.rowcount

        con.commit()
        print(f"Importação concluída. Novas palavras: {inserted_keywords}. "
              f"Novos vínculos: {inserted_links}.")
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

if __name__ == "__main__":
    main()
