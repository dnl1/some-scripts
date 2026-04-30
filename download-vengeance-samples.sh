#!/usr/bin/env bash

set -euo pipefail

BASE_URL_DEFAULT="https://files.lyberry.com/audio/sounds/Vengeance%20Samples/"
DOWNLOAD_PATH_DEFAULT="/mnt/c/Vengeance Samples"

BASE_URL="$BASE_URL_DEFAULT"
DOWNLOAD_PATH="$DOWNLOAD_PATH_DEFAULT"
AUTO_YES=0
INVENTORY_ONLY=0

usage() {
  cat <<'EOF'
Uso:
  ./download-vengeance-samples.sh [opcoes]

Opcoes:
  --base-url URL         URL base da listagem remota
  --download-path PATH   Pasta local de destino
  --yes                  Baixa sem pedir confirmacao
  --inventory-only       Apenas lista o que falta
  --help                 Mostra esta ajuda
EOF
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    printf 'Erro: comando obrigatorio ausente: %s\n' "$cmd" >&2
    exit 1
  fi
}

url_decode() {
  local value="${1//+/ }"
  printf '%b' "${value//%/\\x}"
}

clean_component() {
  local value
  value="$(url_decode "$1")"
  value="${value//\\/_}"
  value="${value//:/_}"
  value="${value//\*/_}"
  value="${value//\?/_}"
  value="${value//\"/_}"
  value="${value//</_}"
  value="${value//>/_}"
  value="${value//|/_}"
  value="${value%%[[:space:]]}"
  value="${value##[[:space:]]}"
  printf '%s' "$value"
}

join_url() {
  local base="$1"
  local href="$2"
  if [[ "$href" =~ ^https?:// ]]; then
    printf '%s' "$href"
    return
  fi
  printf '%s%s' "$base" "$href"
}

sanitize_relative_path() {
  local raw="$1"
  local output=""
  local component
  local first=1

  IFS='/' read -r -a parts <<< "$raw"
  for component in "${parts[@]}"; do
    [[ -z "$component" ]] && continue
    component="$(clean_component "$component")"
    if (( first )); then
      output="$component"
      first=0
    else
      output+="/$component"
    fi
  done

  printf '%s' "$output"
}

fetch_links() {
  local url="$1"
  curl --fail --silent --show-error --location --max-time 60 "$url" \
    | perl -ne 'while(/href=["'"'"']([^"'"'"'#]+)["'"'"']/gi){print "$1\n"}' \
    | while IFS= read -r href; do
        [[ -z "$href" ]] && continue
        [[ "$href" == \?* ]] && continue
        [[ "$href" == /* ]] && continue
        [[ "$href" == *"../"* ]] && continue
        printf '%s\n' "$href"
      done
}

REMOTE_FILES=()
REMOTE_URLS=()

crawl_folder() {
  local url="$1"
  local relative_prefix="$2"
  local href
  local full_url
  local child_relative

  while IFS= read -r href; do
    full_url="$(join_url "$url" "$href")"
    if [[ "$href" == */ ]]; then
      child_relative="${relative_prefix}$(sanitize_relative_path "${href%/}")/"
      crawl_folder "$full_url" "$child_relative"
    else
      child_relative="${relative_prefix}$(sanitize_relative_path "$href")"
      REMOTE_FILES+=("$child_relative")
      REMOTE_URLS+=("$full_url")
    fi
  done < <(fetch_links "$url")
}

ensure_download_path_parent() {
  local parent
  parent="$(dirname "$DOWNLOAD_PATH")"
  if [[ ! -d "$parent" ]]; then
    printf 'Erro: pasta pai nao existe: %s\n' "$parent" >&2
    exit 1
  fi
}

load_local_files() {
  if [[ ! -d "$DOWNLOAD_PATH" ]]; then
    return
  fi

  while IFS= read -r file; do
    LOCAL_FILES+=("${file#./}")
  done < <(cd "$DOWNLOAD_PATH" && find . -type f | sort)
}

print_missing_summary() {
  local index="$1"
  local rel_path="$2"
  local url="$3"
  printf '%s. %s\n' "$index" "$rel_path"
  printf '   origem: %s\n' "$url"
}

confirm_download() {
  local answer
  while true; do
    read -r -p 'Baixar os arquivos faltantes? [s/N] ' answer || return 1
    case "$answer" in
      [sS]|[sS][iI][mM]) return 0 ;;
      [nN]|[nN][aA][oO]|'') return 1 ;;
    esac
  done
}

download_missing() {
  local url="$1"
  local rel_path="$2"
  local target="$DOWNLOAD_PATH/$rel_path"
  local target_dir

  target_dir="$(dirname "$target")"
  mkdir -p "$target_dir"

  if [[ -f "$target" ]]; then
    printf '[Ja existe] %s\n' "$target"
    return
  fi

  printf '[Baixando] %s\n' "$target"
  curl --fail --silent --show-error --location --max-time 300 --output "$target" "$url"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url)
      BASE_URL="$2"
      shift 2
      ;;
    --download-path)
      DOWNLOAD_PATH="$2"
      shift 2
      ;;
    --yes)
      AUTO_YES=1
      shift
      ;;
    --inventory-only)
      INVENTORY_ONLY=1
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      printf 'Opcao invalida: %s\n\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

require_cmd curl
require_cmd perl
require_cmd find
require_cmd sort
ensure_download_path_parent

printf 'Inventariando remoto: %s\n' "$BASE_URL"
crawl_folder "$BASE_URL" ""

if [[ ${#REMOTE_FILES[@]} -eq 0 ]]; then
  printf 'Nenhum arquivo remoto foi encontrado.\n' >&2
  exit 1
fi

declare -a LOCAL_FILES=()
load_local_files

declare -A LOCAL_SET=()
declare -A REMOTE_URL_BY_PATH=()
declare -a MISSING_FILES=()

for local_file in "${LOCAL_FILES[@]:-}"; do
  [[ -n "$local_file" ]] && LOCAL_SET["$local_file"]=1
done

for i in "${!REMOTE_FILES[@]}"; do
  REMOTE_URL_BY_PATH["${REMOTE_FILES[$i]}"]="${REMOTE_URLS[$i]}"
done

for remote_file in "${REMOTE_FILES[@]}"; do
  if [[ -z "${LOCAL_SET[$remote_file]+x}" ]]; then
    MISSING_FILES+=("$remote_file")
  fi
done

IFS=$'\n' MISSING_FILES=( $(printf '%s\n' "${MISSING_FILES[@]}" | sort) )

printf '\nResumo:\n'
printf '  Remotos encontrados: %s\n' "${#REMOTE_FILES[@]}"
printf '  Locais encontrados:  %s\n' "${#LOCAL_FILES[@]}"
printf '  Faltando baixar:    %s\n' "${#MISSING_FILES[@]}"

if [[ ${#MISSING_FILES[@]} -eq 0 ]]; then
  printf '\nTudo ja existe em %s\n' "$DOWNLOAD_PATH"
  exit 0
fi

printf '\nArquivos faltantes:\n'
index=1
for missing_file in "${MISSING_FILES[@]}"; do
  print_missing_summary "$index" "$missing_file" "${REMOTE_URL_BY_PATH[$missing_file]}"
  index=$((index + 1))
done

if (( INVENTORY_ONLY )); then
  printf '\nModo inventario: nenhum download sera iniciado.\n'
  exit 0
fi

printf '\nStatus: os arquivos acima estao disponiveis no indice remoto e podem ser baixados.\n'

if (( ! AUTO_YES )); then
  if ! confirm_download; then
    printf 'Download cancelado pelo usuario.\n'
    exit 0
  fi
fi

for missing_file in "${MISSING_FILES[@]}"; do
  download_missing "${REMOTE_URL_BY_PATH[$missing_file]}" "$missing_file"
done

printf '\nConcluido.\n'
