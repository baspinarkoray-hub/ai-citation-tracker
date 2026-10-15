# AI Citation Tracker — The Block

ChatGPT, Perplexity ve Google AI Overviews'un kripto veri sorularına cevap verirken
**hangi kaynakları gösterdiğini** haftalık ölçer. The Block'un payını rakiplerle karşılaştırır.

## Nasıl çalışır

1. `config/prompts.yaml` → The Block data sayfalarının cevapladığı 49 soru (her biri hedef sayfaya bağlı)
2. `tracker/run.py` → her soruyu her motora 3 kez sorar, cevabı ve kaynak linklerini `data/raw/<tarih>.jsonl`'e yazar
3. `tracker/report.py` → metrikleri hesaplar, `reports/<tarih>.md` raporunu ve `data/summary.json` geçmişini günceller
4. GitHub Actions her pazartesi 08:17 (Madrid) bunu otomatik yapar ve sonuçları repoya commit'ler
5. (Opsiyonel) Make webhook'u özet metrikleri alır → Slack / e-posta / Google Sheets

## Metrikler

| Metrik | Anlamı |
|---|---|
| Cited in % | The Block'un en az bir kez kaynak gösterildiği cevapların oranı |
| Target page hit % | Doğru data sayfasının (prompt'un hedefi) kaynak gösterildiği oran |
| Citation share % | Tüm kaynak linkleri içinde The Block linklerinin payı |
| Mentioned % | Link olmadan da olsa cevap metninde "The Block" geçme oranı |
| Avg position | The Block linkinin kaynak listesindeki ortalama sırası |
| Opportunities | Rakiplerin gösterilip The Block'un hiç gösterilmediği sorular → içerik/teknik iş listesi |

Google AI Overviews her sorguda çıkmaz; oranlar yalnızca overview'un göründüğü sorgular üzerinden hesaplanır, görünme oranı ayrıca raporlanır.

## Kurulum (bir kerelik)

1. GitHub'da **private** bir repo aç (ör. `ai-citation-tracker`) ve bu dosyaları yükle.
2. Repo → **Settings → Secrets and variables → Actions → New repository secret** ile şunları ekle:
   - `OPENAI_API_KEY` — platform.openai.com
   - `PERPLEXITY_API_KEY` — perplexity.ai/settings/api
   - `SERPAPI_API_KEY` — serpapi.com (Google AI Overviews için)
   - `MAKE_WEBHOOK_URL` — opsiyonel, Make'te "Custom webhook" modülünün URL'i
3. **Actions** sekmesi → "Weekly AI citation run" → **Run workflow** → `limit: 5`, `repeats: 1` ile küçük bir test çalıştır.
4. Test temizse bir şey yapmana gerek yok; her pazartesi tam set otomatik çalışır.

## Lokal çalıştırma

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=... PERPLEXITY_API_KEY=... SERPAPI_API_KEY=...
python -m tracker.run --limit 5 --repeats 1     # hızlı test
python -m tracker.run                           # tam set
python -m tracker.report
python -m pytest
```

## Ayarlar

- Model: `OPENAI_MODEL` (varsayılan `gpt-5-mini`), `PERPLEXITY_MODEL` (varsayılan `sonar`)
- Rakip ekle/çıkar: `config/brands.yaml`
- Soru ekle: `config/prompts.yaml` — `id` değerlerini asla değiştirme, yoksa geçmişle karşılaştırma bozulur

## Bilinen sınırlar

- API cevapları, tüketici uygulamalarında (chatgpt.com, Perplexity app) görülen cevaplarla birebir aynı değildir; bu bir **proxy ölçümdür**.
- Cevaplar deterministik değildir; bu yüzden her soru 3 kez sorulur ve oranlar raporlanır.
- AI Overviews resmi API'si olmadığı için SerpApi üzerinden ölçülür (ABD, İngilizce).
