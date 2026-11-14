#!/usr/bin/env bash
# Copia de seguridad del esquema «lotbot» y prueba de restauración.
#
# Lo usa .github/workflows/copia-seguridad.yml y sirve igual en un ordenador.
#
#   copia_seguridad.sh copiar <fichero.sql.gz.enc>
#       Lee BACKUP_DATABASE_URL (solo lectura) y BACKUP_PASSPHRASE, hace
#       pg_dump del esquema lotbot, lo comprime y lo cifra (AES-256-CBC, PBKDF2).
#       Guarda junto a él <fichero>.filas: filas por tabla contadas antes y
#       después de copiar (para comprobar la restauración).
#
#   copia_seguridad.sh verificar <fichero.sql.gz.enc> <URL de una base VACÍA e independiente>
#       Descifra, restaura en esa base y compara las filas de cada tabla con
#       las de <fichero>.filas. NUNCA se debe usar con la base de producción:
#       se niega si la URL de destino es la misma que BACKUP_DATABASE_URL o si
#       la base de destino ya tiene el esquema lotbot.
#
# Herramientas: pg_dump/psql de la misma versión mayor que el servidor o más
# nueva (PG_BIN=/usr/lib/postgresql/18/bin, por ejemplo), gzip y openssl.
set -euo pipefail

PG_BIN="${PG_BIN:-}"
PSQL="${PG_BIN:+$PG_BIN/}psql"
PG_DUMP="${PG_BIN:+$PG_BIN/}pg_dump"
ITER=200000

die() { echo "::error::$*" >&2; exit 1; }
need() { [ -n "${!1:-}" ] || die "Falta $1"; }

# Filas por tabla del esquema lotbot: «tabla filas», una por línea, ordenadas.
count_rows() {
  local url="$1" tables t
  tables=$("$PSQL" "$url" -XAtq -v ON_ERROR_STOP=1 -c \
    "SELECT tablename FROM pg_tables WHERE schemaname = 'lotbot' ORDER BY 1")
  for t in $tables; do
    printf '%s %s\n' "$t" "$("$PSQL" "$url" -XAtq -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM lotbot.\"$t\"")"
  done | LC_ALL=C sort
}

copiar() {
  local out="$1"
  need BACKUP_DATABASE_URL; need BACKUP_PASSPHRASE
  local server client
  server=$("$PSQL" "$BACKUP_DATABASE_URL" -XAtq -c "SHOW server_version_num")
  client=$("$PG_DUMP" --version | grep -oE '[0-9]+' | head -1)
  echo "Servidor PostgreSQL ${server:0:2}, pg_dump $client"
  [ "$client" -ge "$((server / 10000))" ] || die "pg_dump $client es más antiguo que el servidor (${server:0:2}): instala el cliente ${server:0:2}"

  # Todas las tablas de lotbot deben poder leerse (si no, la copia saldría
  # incompleta o vacía por RLS). Ver scripts/sql/usuario_copia.sql.
  local missing
  missing=$("$PSQL" "$BACKUP_DATABASE_URL" -XAtq -v ON_ERROR_STOP=1 -c "
    SELECT coalesce(string_agg(t.tablename, ', '), '') FROM pg_tables t
     WHERE t.schemaname = 'lotbot'
       AND NOT has_table_privilege(format('%I.%I', t.schemaname, t.tablename), 'SELECT')")
  [ -z "$missing" ] || die "El usuario de la copia no puede leer: $missing (ejecuta scripts/sql/usuario_copia.sql)"
  local rls
  rls=$("$PSQL" "$BACKUP_DATABASE_URL" -XAtq -c "SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname = current_user")
  [ "$rls" = "t" ] || die "El usuario de la copia no tiene BYPASSRLS: vería las tablas vacías (ejecuta scripts/sql/usuario_copia.sql)"

  count_rows "$BACKUP_DATABASE_URL" > "$out.antes"
  "$PG_DUMP" "$BACKUP_DATABASE_URL" --schema=lotbot --no-owner --no-privileges \
    | gzip -9 \
    | openssl enc -aes-256-cbc -pbkdf2 -iter "$ITER" -salt -pass env:BACKUP_PASSPHRASE -out "$out"
  count_rows "$BACKUP_DATABASE_URL" > "$out.despues"
  # Mínimo y máximo de cada tabla entre antes y después (la web sigue en marcha).
  LC_ALL=C join "$out.antes" "$out.despues" | awk '{lo=$2<$3?$2:$3; hi=$2>$3?$2:$3; print $1, lo, hi}' > "$out.filas"
  rm -f "$out.antes" "$out.despues"

  local size
  size=$(wc -c < "$out")
  [ "$size" -gt 1000 ] || die "La copia ha salido vacía ($size bytes)"
  openssl enc -d -aes-256-cbc -pbkdf2 -iter "$ITER" -pass env:BACKUP_PASSPHRASE -in "$out" | gunzip \
    | grep "CREATE TABLE lotbot.licenses" > /dev/null || die "La copia no se puede descifrar o no trae las licencias"
  echo "Copia $(basename "$out"): $size bytes, $(wc -l < "$out.filas") tablas."
}

verificar() {
  local file="$1" target="$2"
  need BACKUP_PASSPHRASE
  [ -f "$file.filas" ] || die "Falta $file.filas"
  [ "$target" != "${BACKUP_DATABASE_URL:-}" ] || die "El destino es la base de producción: no se restaura ahí"
  local existing
  existing=$("$PSQL" "$target" -XAtq -c "SELECT count(*) FROM pg_namespace WHERE nspname = 'lotbot'")
  [ "$existing" = "0" ] || die "La base de destino ya tiene el esquema lotbot: usa una base vacía"

  openssl enc -d -aes-256-cbc -pbkdf2 -iter "$ITER" -pass env:BACKUP_PASSPHRASE -in "$file" | gunzip \
    | "$PSQL" "$target" -Xq -v ON_ERROR_STOP=1 --single-transaction > /dev/null

  count_rows "$target" > "$file.restaurada"
  local bad=0 table lo hi got
  while read -r table lo hi; do
    got=$(awk -v t="$table" '$1 == t {print $2}' "$file.restaurada")
    if [ -z "$got" ] || [ "$got" -lt "$lo" ] || [ "$got" -gt "$hi" ]; then
      echo "::error::$table: restauradas ${got:-0} filas; en origen $lo-$hi"
      bad=1
    else
      echo "  $table: $got filas"
    fi
  done < "$file.filas"
  [ "$(wc -l < "$file.restaurada")" -eq "$(wc -l < "$file.filas")" ] || { echo "::error::Distinto número de tablas"; bad=1; }
  [ "$bad" = 0 ] || die "La restauración no coincide con el origen"
  echo "Restauración comprobada: $(wc -l < "$file.filas") tablas con las mismas filas."
}

case "${1:-}" in
  copiar) copiar "${2:?fichero de salida}" ;;
  verificar) verificar "${2:?fichero}" "${3:?URL de la base de destino}" ;;
  *) echo "Uso: $0 copiar <fichero> | verificar <fichero> <url-destino>" >&2; exit 2 ;;
esac
