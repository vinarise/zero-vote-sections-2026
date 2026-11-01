# Independent recount of round 2, President, from one raw TSE section file. Shares no code with the record.
#   unzip -p votacao_secao_2026_BR.zip votacao_secao_2026_BR.csv | LC_ALL=C awk -v year=2026 -v pt=13 -v opp=22 -f recount.awk
# The PL side's ballot number is 17 in 2018 and 22 in 2022 and 2026. The PT side's is 13.
# Columns: 6 NR_TURNO, 11 SG_UF, 14 CD_MUNICIPIO, 16 NR_ZONA, 17 NR_SECAO, 18 CD_CARGO, 20 NR_VOTAVEL, 22 QT_VOTOS.
# It fails, exit 1, on an unexpected header or when no section of round 2 is read.
BEGIN { FS = ";" }
# 2022 quotes every field, 2026 and 2018 only the text. Quotes go before the fields are read.
{ gsub(/"/, "") }
NR == 1 { if ($6 != "NR_TURNO" || $17 != "NR_SECAO" || $20 != "NR_VOTAVEL" || $22 != "QT_VOTOS") { print "unexpected header" > "/dev/stderr"; bad = 1; exit 1 } next }
{ nf[NF]++ }
$6 == 2 && $18 == 1 {
  k = $11 FS $14 FS $16 FS $17
  seen[k] = 1
  if ($20 == pt) P[k] += $22
  else if ($20 == opp) O[k] += $22
}
END {
  if (bad) exit 1
  for (k in seen) {
    sections++
    n = P[k] + O[k]; tp += P[k]; to += O[k]
    for (i = 1; i <= 3; i++) {
      m = (i == 1 ? 1 : (i == 2 ? 10 : 50))
      if (n >= m) { valid[m]++; if (O[k] == 0) { zo[m]++; vo[m] += P[k] } if (P[k] == 0) { zp[m]++; vp[m] += O[k] } }
    }
  }
  if (sections == 0) { printf "year %s: no section of round 2 was read\n", year > "/dev/stderr"; exit 1 }
  printf "year %s: sections with a round-2 row %d, votes pt %d, votes opp %d, margin %d\n", year, sections, tp, to, tp - to
  for (i = 1; i <= 3; i++) {
    m = (i == 1 ? 1 : (i == 2 ? 10 : 50))
    printf "  at least %2d valid votes: sections %d, zero for opp %d (pt votes in them %d), zero for pt %d (opp votes in them %d)\n", m, valid[m], zo[m], vo[m], zp[m], vp[m]
  }
}
