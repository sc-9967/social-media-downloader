# Social Media Downloader

Piccola applicazione web da avviare sul proprio computer: incolli il link di un post
pubblico di **TikTok**, **Instagram** o **Facebook** e il browser scarica il video o
le immagini. Se il post contiene più elementi (carosello, slideshow) ricevi uno ZIP.

Spuntando **Riduci ogni file a massimo 9,9 MB**, ogni video o immagine più grande
viene compresso fino a stare sotto 9.900.000 byte (vale per ciascun file, anche
dentro lo ZIP). I video vengono ricodificati in H.264 abbassando bitrate e, se serve,
risoluzione; le immagini vengono convertite in JPEG e ridimensionate. Un video
molto lungo può non entrare nel limite: in quel caso compare un errore.

Sotto il cofano usa [yt-dlp](https://github.com/yt-dlp/yt-dlp) per i video e
[gallery-dl](https://github.com/mikf/gallery-dl) come ripiego per i post di sole immagini.

## Requisiti

- Python 3.10 o superiore
- Nessun ffmpeg da installare: se non è nel `PATH` viene usato quello incluso in
  `imageio-ffmpeg`

## Avvio

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

Apri <http://localhost:8000>, incolla il link e premi **Scarica**.

### Con Docker

```bash
docker build -t social-media-downloader .
docker run --rm -p 8000:8000 social-media-downloader
```

## Limiti noti

- **Solo contenuti pubblici.** L'app non usa il login. Se la piattaforma chiede
  l'accesso, compare un messaggio di errore.
- **TikTok** al momento può rimandare alla pagina di login anche per video pubblici,
  a seconda della rete e della regione: in quel caso il download non riesce.
- Le piattaforme cambiano spesso il loro funzionamento. Se i download smettono di
  funzionare, aggiorna i motori di estrazione:

  ```bash
  pip install -U yt-dlp gallery-dl
  ```

- È pensata per l'uso personale sul proprio computer. Non esporla su internet
  senza autenticazione e limiti di utilizzo.

## Test

```bash
pip install -r requirements-dev.txt
pytest
```

## Uso responsabile

Scarica solo contenuti di cui possiedi i diritti o per i quali hai il permesso
dell'autore, nel rispetto dei termini di servizio delle piattaforme e delle leggi
sul diritto d'autore. Gli autori del software non sono responsabili dell'uso che
ne viene fatto.

## Licenza

[MIT](LICENSE)
