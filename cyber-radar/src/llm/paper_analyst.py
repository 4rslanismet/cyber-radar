"""Level 3-4: Derin makale analizi.

Orijinal mimarideki Paper Analyst Agent + Research Agent'ı tek bir güçlü model
çağrısında birleştiriyoruz (tek sunucuda her makale için 2 ayrı reasoning
çağrısı yapmak maliyeti gereksiz yere ikiye katlar; alanlar yeterince
ayrıştırılmış olduğu için tek çağrı pratikte yeterli sonuç verir).

full_text verilirse (PDF çözüldüyse) ona öncelik verilir; verilmezse yalnızca
abstract ile ABSTRACT_ONLY seviyesinde analiz yapılır - bu durum modele açıkça
belirtilir ki alanları abstract'tan uydurmasın.
"""
from __future__ import annotations

from .. import config
from .client import call_json

_SYSTEM = """Sen bir siber güvenlik akademik makale analistisin. Görevin verilen
makaleden yapılandırılmış bilgi çıkarmak.

KURAL: Metinde açıkça belirtilmeyen hiçbir bilgiyi uydurma. Bir alan için bilgi
yoksa o alanı boş liste ([]) ya da null bırak, tahmin üretme.

Yalnızca şu şemada geçerli JSON döndür, başka hiçbir metin ekleme:
{
  "research_problem": string | null,
  "objective": string | null,
  "contributions": [string],
  "methodology": string | null,
  "datasets": [string],
  "tools": [string],
  "models": [string],
  "baselines": [string],
  "metrics": [string],
  "key_results": [string],
  "limitations": [string],
  "future_work": [string],
  "research_gap": [string],
  "potential_research_ideas": [string],
  "code_repository": string | null,
  "novelty_score": number,          // 0-10, sadece metinden çıkarılabiliyorsa
  "academic_value_score": number,   // 0-10
  "reproducibility": string | null  // "high" | "medium" | "low" | null
}"""


def analyze_paper(title: str, abstract: str | None, full_text: str | None, analysis_type: str) -> dict:
    if full_text:
        body = f"[TAM METİN - analysis_type=FULL_TEXT]\n\n{full_text[:60000]}"
    else:
        body = (
            f"[YALNIZCA ÖZET - analysis_type=ABSTRACT_ONLY. Tam metin yok, "
            f"yalnızca başlık ve özetten çıkarılabilecek kadarını doldur, "
            f"kalanları null/[] bırak.]\n\nÖzet: {abstract or '(özet yok)'}"
        )
    content = f"Başlık: {title}\n\n{body}"
    result = call_json(config.ANALYSIS_MODEL, _SYSTEM, content, max_output_tokens=3000)
    result["_analysis_type"] = analysis_type
    return result
