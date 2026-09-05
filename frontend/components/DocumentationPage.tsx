"use client";

import {
  BookOpenCheck,
  ChevronRight,
  DatabaseBackup,
  ExternalLink,
  KeyRound,
  MailCheck,
  Search,
  ShieldCheck,
  TerminalSquare,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import PageHeader from "./PageHeader";

type ReadItem = { name: string; meaning: string };
type PageGuide = {
  id: string;
  name: string;
  href: string;
  purpose: string;
  cards: ReadItem[];
  practice?: string;
};

const pageGuides: PageGuide[] = [
  {
    id: "overview",
    name: "Overview",
    href: "/",
    purpose: "Ringkasan nasional untuk melihat incident aktif, sumber bukti, risiko, wilayah, dan TBBM yang terpapar dalam satu layar.",
    cards: [
      { name: "Active Incidents", meaning: "Jumlah incident berstatus OPEN atau MONITORING setelah filter diterapkan." },
      { name: "Critical Incidents", meaning: "Incident aktif pada band CRITICAL; memakai Supply Risk untuk gangguan pasokan dan HSSE Risk untuk kejadian HSSE." },
      { name: "News 24H", meaning: "Jumlah bukti News pada incident aktif yang menerima aktivitas sinyal dalam 24 jam terakhir." },
      { name: "TikTok Signals 24H", meaning: "Jumlah bukti TikTok pada incident aktif yang menerima aktivitas sinyal dalam 24 jam terakhir; tetap early signal, bukan fakta terverifikasi." },
      { name: "Supply Incidents", meaning: "Incident aktif berkategori SUPPLY_DISRUPTION." },
      { name: "Reported MT Accidents", meaning: "Kejadian HSSE transportasi yang terlaporkan media; bukan total populasi kecelakaan aktual." },
      { name: "Provinces Affected", meaning: "Jumlah provinsi unik dari incident aktif yang lokasi provinsinya berhasil di-resolve." },
      { name: "TBBM Exposed", meaning: "Jumlah TBBM verified unik yang berelasi sebagai nearest atau serving terminal. Paparan tidak berarti penyebab." },
      { name: "7-day incident signal trend", meaning: "Tinggi batang adalah jumlah signal. Label S adalah signal dan I adalah incident yang pertama terdeteksi pada tanggal itu; klik batang untuk memfilter peta." },
      { name: "Situation brief", meaning: "Ringkasan deterministik dari analytics tersimpan, bukan hasil penelusuran web mandiri." },
      { name: "Trending issues", meaning: "Peringkat event type berdasarkan jumlah incident aktif; klik baris untuk memfilter peta." },
    ],
    practice: "Gunakan filter global lebih dahulu, lalu kombinasikan batang tanggal dan Trending issues. Klik lagi atau pilih Hapus filter peta untuk kembali ke seluruh hasil.",
  },
  {
    id: "situation-map",
    name: "Situation Map",
    href: "/situation-map",
    purpose: "Ruang kerja geospasial dengan tiga tab: titik incident, konsentrasi wilayah, dan paparan TBBM tanpa me-remount peta.",
    cards: [
      { name: "Generated at", meaning: "Waktu server membentuk respons analytics yang sedang dibaca." },
      { name: "Unresolved province incidents", meaning: "Incident aktif yang belum memiliki provinsi canonical; gunakan angka ini sebagai antrean perbaikan kualitas lokasi." },
      { name: "Rentang data peta", meaning: "Tanggal signal paling awal sampai paling akhir dari titik yang benar-benar tampil." },
      { name: "Peta", meaning: "Kuning = supply, merah = laporan kecelakaan MT, biru = gangguan eksternal, hijau = master TBBM. Marker bernomor memuat beberapa incident pada koordinat sama." },
      { name: "Structured analytics", meaning: "Baris dan marker berasal dari data yang sama. Klik baris pada tab Situation Map untuk menyorot marker; cari, urutkan, dan ubah jumlah baris tanpa mengubah sumber data." },
      { name: "Geographic Intelligence", meaning: "Baca incidents sebagai jumlah kejadian per provinsi/regency; News dan TikTok sebagai jumlah bukti, Critical sebagai jumlah band kritis, Average Risk sebagai rata-rata risk kontekstual." },
      { name: "TBBM Incident Exposure", meaning: "Incidents, affected SPBU, News/TikTok, dan Average Risk adalah hubungan incident dengan nearest/serving TBBM, bukan bukti terminal menyebabkan kejadian." },
    ],
  },
  {
    id: "incidents",
    name: "Incidents & Incident Detail",
    href: "/incidents",
    purpose: "Register kejadian dunia nyata yang menggabungkan satu atau lebih signal News/TikTok, dengan halaman detail untuk lineage dan audit.",
    cards: [
      { name: "Risk badge", meaning: "0–24 NORMAL, 25–44 WATCH, 45–64 WARNING, 65–79 HIGH, 80–100 CRITICAL. Skor mengikuti kategori incident." },
      { name: "News / TikTok", meaning: "Jumlah signal per kanal yang mendukung incident; banyak signal tidak sama dengan banyak incident." },
      { name: "Confidence", meaning: "Keyakinan ekstraksi/koroborasi 0–100%, bukan probabilitas bahwa semua detail berita benar." },
      { name: "Trend", meaning: "Arah perubahan velocity signal: DECLINING, STABLE, INCREASING, atau RAPIDLY_INCREASING." },
      { name: "Source corroboration", meaning: "Daftar bukti asli beserta primary signal, confidence, dan link publik. FALSE POSITIVE disimpan untuk audit tetapi dikeluarkan dari intelligence." },
      { name: "TBBM matching", meaning: "Nearest adalah jarak garis lurus PostGIS; Serving berasal dari master operasional dan tidak diinferensikan dari jarak." },
      { name: "Risk history", meaning: "Perubahan skor tersimpan dari kalkulasi pertama hingga terbaru; tinggi batang memakai nilai terbesar dari Supply/HSSE pada titik waktu itu." },
      { name: "Notifications", meaning: "Status job email untuk incident: PENDING/RETRY sedang menunggu, SENT berhasil, FAILED perlu melihat error atau reconnect akun." },
    ],
  },
  {
    id: "signals",
    name: "News Signals",
    href: "/news",
    purpose: "Register bukti News sebagai lapisan koroborasi yang diproses melalui pipeline incident yang sama.",
    cards: [
      { name: "Published / Source", meaning: "Waktu publikasi dan identitas sumber. Badge LIVE membedakan data nyata dari legacy demo." },
      { name: "Classification", meaning: "Event terstruktur hasil pipeline; tanda — berarti belum terklasifikasi atau tidak lolos." },
      { name: "Location", meaning: "Teks lokasi hasil ekstraksi; Unresolved berarti belum cocok dengan master/geocoding." },
      { name: "Relevance", meaning: "Kesesuaian bukti News terhadap konteks distribusi BBM dalam persen." },
      { name: "Incident", meaning: "Kode incident tujuan setelah clustering. Not linked berarti signal belum atau tidak digabungkan." },
    ],
  },
  {
    id: "analytics",
    name: "Product & Event Intelligence",
    href: "/product-intelligence",
    purpose: "Membandingkan distribusi incident menurut produk BBM dan event type di dalam filter yang sama.",
    cards: [
      { name: "Product table", meaning: "Incidents adalah kejadian unik; News/TikTok Mentions adalah jumlah bukti; Critical adalah kejadian kritis; Average Risk adalah rata-rata skor; Trend merangkum arah mayoritas incident." },
      { name: "Event table", meaning: "Current 24H dibandingkan Previous 24H untuk membaca percepatan; Current 7D menunjukkan basis kejadian pada jendela terpilih; Average Risk menunjukkan intensitas rata-rata." },
    ],
  },
  {
    id: "hsse",
    name: "HSSE",
    href: "/hsse",
    purpose: "Intelligence khusus kecelakaan mobil tangki yang diberitakan media, bukan denominator kinerja keselamatan aktual.",
    cards: [
      { name: "Reported MT Accidents", meaning: "Jumlah incident HSSE terlaporkan dalam filter." },
      { name: "Fatalities / Injuries", meaning: "Jumlah incident yang memiliki indikasi korban meninggal/luka pada evidence, bukan penjumlahan jumlah korban orang." },
      { name: "Fire / Fuel Spill / Road Blockage", meaning: "Jumlah incident dengan konsekuensi tersebut pada sedikitnya satu evidence." },
      { name: "Incident table", meaning: "Gunakan risk dan severity untuk prioritas triage, lalu verifikasi evidence pada Incident Detail." },
    ],
  },
  {
    id: "alerts",
    name: "Alerts",
    href: "/alerts",
    purpose: "Audit alert WhatsApp setelah rule, threshold, cooldown, deduplication, dan escalation diterapkan.",
    cards: [
      { name: "Risk / Severity", meaning: "Skor dan band pada saat alert diputuskan, sehingga dapat berbeda dari skor incident terbaru." },
      { name: "Delivery Status", meaning: "QUEUED/RETRY menunggu pengiriman, SENT/MOCK_SENT berhasil sesuai provider, FAILED memerlukan pemeriksaan error." },
      { name: "Provider Message ID", meaning: "Referensi balasan provider untuk audit; bukan bukti penerima sudah membaca pesan." },
    ],
  },
  {
    id: "discovery-overview",
    name: "TikTok Discovery — Overview",
    href: "/tiktok-discovery",
    purpose: "Monitoring kandidat publik, relevansi, incident, dan konsumsi credit ScrapeCreators.",
    cards: [
      { name: "Videos Discovered", meaning: "Seluruh video unik yang terlihat provider pada periode." },
      { name: "New Videos", meaning: "Video yang baru ditambahkan setelah dedup provider/video ID." },
      { name: "Relevant Videos", meaning: "Video yang lolos relevance screen dan dapat masuk pipeline canonical." },
      { name: "TikTok Incidents", meaning: "Incident yang terkait hasil discovery; tidak berarti semuanya dibuat baru pada periode itu." },
      { name: "Credits Today / This Month", meaning: "Pemakaian credit provider yang terekam per physical request." },
      { name: "Credit controls", meaning: "Search/Transcript memisahkan sumber biaya; Credits per Relevant/Incident membantu menilai efisiensi; projection bukan tagihan final." },
      { name: "Charts", meaning: "Baca panjang batang relatif dalam panel yang sama untuk tren waktu, kategori, keyword, dan lokasi teratas." },
    ],
  },
  {
    id: "tiktok-public-signals",
    name: "TikTok public signals",
    href: "/tiktok-discovery/public-signals",
    purpose: "Register bukti publik TikTok yang sudah masuk ke pipeline canonical; tetap early signal yang belum terverifikasi dan media tidak diunduh.",
    cards: [
      { name: "Published / Creator", meaning: "Waktu publikasi dan akun pembuat konten publik. Badge LIVE membedakan data nyata dari legacy demo." },
      { name: "Caption / Reach", meaning: "Caption dan hashtag adalah bukti teks; views adalah metadata jangkauan saat data dikumpulkan, bukan ukuran kebenaran." },
      { name: "Classification / Location", meaning: "Event dan lokasi adalah hasil ekstraksi pipeline; tanda — atau Unresolved berarti belum berhasil dipetakan." },
      { name: "Confidence", meaning: "Keyakinan pipeline dalam persen, bukan verifikasi bahwa klaim di dalam konten benar." },
      { name: "Incident", meaning: "Kode incident tujuan setelah clustering. Not linked berarti signal belum atau tidak digabungkan." },
    ],
  },
  {
    id: "early-warning",
    name: "TikTok Early Warning",
    href: "/tiktok-discovery/early-warning",
    purpose: "Mengukur urutan waktu TikTok terhadap News hanya untuk incident yang memiliki bukti lintas sumber.",
    cards: [
      { name: "Average / Median Lead Time", meaning: "Nilai positif berarti TikTok lebih dahulu; negatif berarti News lebih dahulu. Median lebih tahan terhadap pencilan." },
      { name: "TikTok First %", meaning: "Persentase incident dengan TikTok lebih cepat lebih dari 5 menit." },
      { name: "News First %", meaning: "Persentase incident dengan News lebih cepat lebih dari 5 menit." },
      { name: "Simultaneous %", meaning: "Persentase incident dengan selisih waktu maksimal 5 menit." },
      { name: "By Event", meaning: "Rata-rata menit lead/lag per event type; jangan dibaca sebagai verifikasi kebenaran konten TikTok." },
    ],
  },
  {
    id: "discovery-workflow",
    name: "TikTok Discovery — Keywords, Manual, Videos & Runs",
    href: "/tiktok-discovery/keywords",
    purpose: "Mengelola cakupan pencarian, melakukan pencarian ad-hoc, meninjau video, dan mengaudit setiap request provider.",
    cards: [
      { name: "Keywords", meaning: "Interval efektif memakai Global kecuali override. Last/Next Run menunjukkan scheduler; Results/New/Relevant adalah hasil run terakhir." },
      { name: "Manual Search", meaning: "Tetap membuat run audit, dedup, screening, enrichment selektif, dan incident matching; Max Pages membatasi biaya." },
      { name: "Videos", meaning: "Engagement adalah metadata saat discovery; Relevance adalah skor pipeline; Location/TBBM harus dibaca bersama status resolusi." },
      { name: "Runs", meaning: "API adalah jumlah request, Credits adalah konsumsi, Results hasil mentah, New hasil dedup, Relevant hasil screening, Transcripts hasil enrichment, Incidents hasil pipeline." },
      { name: "Run detail", meaning: "Timeline mengungkap operation, durasi, credit, status, dan error per request sehingga HTTP 402 dapat dibedakan dari error aplikasi." },
    ],
  },
  {
    id: "discovery-settings",
    name: "TikTok Discovery — Settings",
    href: "/tiktok-discovery/settings",
    purpose: "Menyimpan API key secara terenkripsi, mengatur schedule/search/enrichment, dan melindungi credit.",
    cards: [
      { name: "Provider", meaning: "Connection harus HEALTHY sebelum discovery diaktifkan. API key yang tersimpan hanya ditampilkan sebagai masked state." },
      { name: "Discovery Schedule", meaning: "Global Interval dipakai keyword tanpa override; Adaptive Scheduling dapat mempercepat sementara tanpa mengubah nilai user." },
      { name: "Default Search", meaning: "Region, date, sort, dan Max Pages menjadi default. Transcript dapat menambah kualitas; AI fallback dapat memakai credit lebih besar; media download sebaiknya OFF." },
      { name: "API Credit Management", meaning: "Warning memberi peringatan; Critical menunda LOW; setelah limit hanya HIGH yang dapat berjalan sesuai guard." },
      { name: "Provider Health", meaning: "Last Successful Request dan Last Error menunjukkan kondisi terakhir; Requests/Credits adalah observability, bukan saldo provider." },
    ],
  },
  {
    id: "tbbm",
    name: "Master Data — TBBM / Fuel Terminal",
    href: "/master-data/tbbm",
    purpose: "Mengelola registry geospasial terverifikasi melalui tahap discovery → candidate → review → master.",
    cards: [
      { name: "Total Terminal", meaning: "Semua master yang belum soft-deleted, termasuk NEED_REVIEW." },
      { name: "Verified", meaning: "Master yang boleh dipakai incident, map, analytics, exposure, dan nearest-TBBM." },
      { name: "Need Review", meaning: "Master belum disetujui operator dan belum boleh dipakai operasional." },
      { name: "TBBM / Fuel Terminal / Integrated Terminal / Depot BBM / TLPG", meaning: "Distribusi tipe record; tipe tidak menggantikan status Verified dan Operational." },
      { name: "Discovery job", meaning: "Progress = completed queries / total queries. Raw dapat berulang; Unique telah didedup; Possible Duplicates wajib review; Failed dapat di-retry." },
      { name: "Candidate match", meaning: "Distance dan Similarity hanya petunjuk. Pilih Merge, Keep Both, Reject, atau Approve secara eksplisit." },
      { name: "Keyword Performance", meaning: "Bandingkan Raw Places, Unique Candidates, dan Approved Terminals untuk menilai presisi keyword." },
    ],
  },
  {
    id: "system",
    name: "System Monitor",
    href: "/system",
    purpose: "Memantau health API/PostgreSQL/Redis, heartbeat worker, queue, delivery, dan freshness analytics.",
    cards: [
      { name: "API / PostgreSQL / Redis", meaning: "HEALTHY berarti probe terakhir berhasil; status ini tidak menjamin setiap provider eksternal tersedia." },
      { name: "Service heartbeats", meaning: "Last seen harus terus bergerak. Queue depth yang naik terus menandakan backlog pada worker terkait." },
      { name: "Pipeline queues", meaning: "Jumlah task menunggu per queue; baca bersama heartbeat agar queue nol tidak disalahartikan saat worker mati." },
      { name: "WhatsApp delivery success", meaning: "Rasio hasil delivery tersimpan; mock provider dapat menghasilkan keberhasilan simulasi." },
      { name: "Last analytics refresh", meaning: "Waktu agregat analytics terakhir dibangun; data raw dapat lebih baru daripada timestamp ini." },
    ],
  },
  {
    id: "settings",
    name: "Settings",
    href: "/settings",
    purpose: "Administrasi source, keyword, master pendukung, risk/rule, notification, provider, dan scheduler.",
    cards: [
      { name: "News Sources", meaning: "Satu feed_url adalah satu identitas source. Priority 1 tertinggi; Credibility adalah bobot sumber; Last Error tidak menghapus data lama." },
      { name: "News Keywords", meaning: "Phrase aktif memfilter koleksi berikutnya. Edit/hapus tidak menghapus artikel historis karena lifecycle memakai soft delete." },
      { name: "Provider cards", meaning: "Ready berarti credential tersedia; masked/Configured tidak mengungkap nilai key. Test connection tetap diperlukan untuk memastikan izin API." },
      { name: "Scheduler", meaning: "Interval adalah cadence default worker. TikTok keyword dapat override; semua waktu operasional mengikuti Asia/Jakarta kecuali timestamp API berformat UTC." },
      { name: "Notifications · Email", meaning: "General = channel health, Provider Setup = OAuth app, Accounts = sender, Recipients/Groups = tujuan, Alert Rules = kondisi, Logs = audit attempt." },
    ],
  },
];

const steps = [
  "Install Docker Desktop atau Docker Engine dengan Compose v2.",
  "Clone repository, masuk ke folder project, lalu jalankan ./install.sh.",
  "Installer memvalidasi checksum snapshot, membuat .env dengan secret lokal unik bila belum ada, mengaktifkan hook Git, build image, dan menunggu seluruh service healthy.",
  "Pada volume PostgreSQL baru, snapshot Git dipulihkan otomatis sebelum API mulai. Pada volume lama, data yang ada dipertahankan dan snapshot tidak menimpa database.",
  "Buka http://localhost/documentation, kemudian konfigurasi credential provider milik deployment melalui UI.",
];

function NumberedSteps({ items }: { items: string[] }) {
  return <ol className="mt-5 space-y-3">{items.map((item, index) => <li key={item} className="flex gap-3 text-sm leading-6 text-slate-600"><span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-ink text-[10px] font-black text-white">{index + 1}</span><span>{item}</span></li>)}</ol>;
}

function SectionTitle({ eyebrow, title, description }: { eyebrow: string; title: string; description: string }) {
  return <div><div className="eyebrow">{eyebrow}</div><h2 className="mt-1 font-serif text-2xl">{title}</h2><p className="mt-2 max-w-4xl text-sm leading-6 text-slate-500">{description}</p></div>;
}

export default function DocumentationPage() {
  const [query, setQuery] = useState("");
  const filteredGuides = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("id-ID");
    if (!normalized) return pageGuides;
    return pageGuides.filter((guide) => [guide.name, guide.purpose, guide.practice, ...guide.cards.flatMap((card) => [card.name, card.meaning])].some((value) => value?.toLocaleLowerCase("id-ID").includes(normalized)));
  }, [query]);

  return <div className="px-5 pb-12 pt-5 md:px-8 lg:px-10 lg:pt-6">
    <PageHeader eyebrow="Operator handbook" title="Documentation" description="Panduan instalasi, snapshot database, konfigurasi provider, email notification, fungsi setiap page, dan cara membaca card." />

    <section className="mb-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {[
        ["#installation", "Install system", "Docker + bootstrap data", TerminalSquare],
        ["#database-snapshot", "Database snapshot", "TBBM + seluruh signal", DatabaseBackup],
        ["#provider-keys", "Provider keys", "Google + ScrapeCreators", KeyRound],
        ["#email-notification", "Email notification", "Gmail + Microsoft", MailCheck],
      ].map(([href, title, copy, Icon]) => <a key={String(href)} href={String(href)} className="panel group flex items-center gap-3 p-4 hover:border-petrol/30"><span className="grid h-10 w-10 place-items-center rounded-xl bg-blue-50 text-petrol"><Icon size={19}/></span><span className="min-w-0"><strong className="block text-sm">{String(title)}</strong><small className="text-slate-400">{String(copy)}</small></span><ChevronRight className="ml-auto text-slate-300 group-hover:text-petrol" size={16}/></a>)}
    </section>

    <section id="installation" className="panel scroll-mt-24 p-5 md:p-7">
      <SectionTitle eyebrow="01 · System installer" title="Instalasi sekali jalan" description="Installer ditujukan untuk macOS/Linux atau Windows melalui WSL/Git Bash dengan Docker Desktop. Tidak memerlukan PostgreSQL, Redis, Python, atau Node di host." />
      <NumberedSteps items={steps}/>
      <div className="mt-6 rounded-xl bg-slate-950 p-4 font-mono text-xs leading-6 text-slate-100"><span className="text-lime">git clone</span> &lt;repository-url&gt;<br/><span className="text-lime">cd</span> newspaper<br/><span className="text-lime">./install.sh</span></div>
      <div className="mt-5 grid gap-3 sm:grid-cols-3">{[["Dashboard","http://localhost"],["Documentation","http://localhost/documentation"],["API readiness","http://localhost/ready"]].map(([name, value]) => <div key={name} className="rounded-xl border border-slate-200 p-4"><div className="text-[9px] font-black uppercase tracking-wider text-slate-400">{name}</div><div className="mt-2 break-all text-xs font-bold">{value}</div></div>)}</div>
    </section>

    <section id="database-snapshot" className="panel mt-5 scroll-mt-24 p-5 md:p-7">
      <SectionTitle eyebrow="02 · Data portability" title="Snapshot database pada setiap commit" description="Snapshot PostgreSQL custom archive disimpan di Git bersama manifest dan checksum. Snapshot mencakup schema, TBBM, News/TikTok, signal, event, incident, analytics, serta histori discovery." />
      <div className="mt-5 grid gap-4 lg:grid-cols-3">
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4"><ShieldCheck className="text-emerald-700" size={20}/><h3 className="mt-3 text-sm font-bold text-emerald-950">Aman untuk instalasi baru</h3><p className="mt-2 text-xs leading-5 text-emerald-900">Restore hanya berjalan saat PostgreSQL membuat volume kosong. Restart atau upgrade biasa tidak menghapus database yang sudah ada.</p></div>
        <div className="rounded-xl border border-blue-200 bg-blue-50 p-4"><DatabaseBackup className="text-petrol" size={20}/><h3 className="mt-3 text-sm font-bold">Fail-closed commit</h3><p className="mt-2 text-xs leading-5 text-slate-600">Hook commit gagal bila PostgreSQL tidak aktif atau snapshot tidak valid, sehingga commit normal selalu membawa keadaan database terbaru.</p></div>
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4"><KeyRound className="text-amber-700" size={20}/><h3 className="mt-3 text-sm font-bold text-amber-950">Credential tidak ikut Git</h3><p className="mt-2 text-xs leading-5 text-amber-900">API key TikTok, OAuth client secret/token, akun/penerima/rule email, dan tujuan alert dibersihkan dari salinan kerja sebelum dump final.</p></div>
      </div>
      <div className="mt-5 rounded-xl bg-slate-950 p-4 font-mono text-xs leading-6 text-slate-100"><span className="text-lime">make snapshot</span>        # refresh manual<br/><span className="text-lime">make verify-snapshot</span> # checksum + archive<br/><span className="text-lime">make hooks</span>           # aktifkan ulang hook Git</div>
      <p className="mt-4 text-xs leading-5 text-slate-500">File canonical: <code>database/bootstrap.dump</code> dan <code>database/bootstrap.manifest</code>. Jangan gunakan <code>docker compose down -v</code> kecuali benar-benar ingin menghapus volume lokal; command itu destruktif.</p>
    </section>

    <section id="provider-keys" className="panel mt-5 scroll-mt-24 p-5 md:p-7">
      <SectionTitle eyebrow="03 · External providers" title="Google Maps dan ScrapeCreators" description="Semua request provider dilakukan backend. Browser hanya mengirim key ke proxy same-origin untuk dites dan disimpan terenkripsi; key tidak pernah dibaca kembali oleh UI." />
      <div className="mt-6 grid gap-5 xl:grid-cols-2">
        <article className="rounded-2xl border border-slate-200 p-5">
          <div className="flex items-center justify-between gap-3"><h3 className="font-serif text-xl">Google Maps Platform</h3><a href="https://developers.google.com/maps/documentation/places/web-service/get-api-key" target="_blank" rel="noreferrer" className="flex items-center gap-1 text-[10px] font-bold text-petrol">Official setup <ExternalLink size={11}/></a></div>
          <NumberedSteps items={[
            "Buat/pilih Google Cloud project dan aktifkan billing.",
            "Enable Geocoding API dan Places API (New). Aplikasi tidak memerlukan Maps JavaScript API untuk Leaflet.",
            "Buka APIs & Services → Credentials → Create credentials → API key.",
            "Restrict key ke IP/backend deployment dan API restrictions hanya Geocoding API + Places API (New). Untuk localhost, gunakan pembatasan yang sesuai environment uji.",
            "Di aplikasi buka Settings → Geocoding → Configure API key, paste key, lalu pilih Test connection & save.",
            "Buka Master Data → TBBM → Google Maps Settings atau Get Data TBBM untuk memastikan Places API (New) juga berhasil.",
          ]}/>
        </article>
        <article className="rounded-2xl border border-slate-200 p-5">
          <div className="flex items-center justify-between gap-3"><h3 className="font-serif text-xl">ScrapeCreators</h3><a href="https://app.scrapecreators.com/" target="_blank" rel="noreferrer" className="flex items-center gap-1 text-[10px] font-bold text-petrol">Provider dashboard <ExternalLink size={11}/></a></div>
          <NumberedSteps items={[
            "Daftar atau sign in di app.scrapecreators.com dan salin API key dari dashboard; jangan kirim key melalui chat atau commit ke file.",
            "Di aplikasi buka TikTok Discovery → Settings dan pastikan provider ScrapeCreators.",
            "Paste API key pada field API Key, pilih Test Connection, lalu Save Settings.",
            "Atur Daily/Monthly Credit Limit dan threshold sebelum mengaktifkan Discovery.",
            "Aktifkan minimal satu keyword, lalu Run. Periksa TikTok Discovery → Runs dan Provider Health.",
            "HTTP 402 berarti credit/billing provider habis; itu berbeda dari credential invalid atau kerusakan aplikasi.",
          ]}/>
          <a href="https://docs.scrapecreators.com/integrations/cli/" target="_blank" rel="noreferrer" className="mt-4 inline-flex items-center gap-1 text-xs font-bold text-petrol">Dokumentasi autentikasi x-api-key <ExternalLink size={12}/></a>
        </article>
      </div>
    </section>

    <section id="email-notification" className="panel mt-5 scroll-mt-24 p-5 md:p-7">
      <SectionTitle eyebrow="04 · Notifications" title="Mengaktifkan email notification" description="Email memakai OAuth send-only: Gmail API untuk Google atau Microsoft Graph untuk Outlook/Exchange. Password mailbox dan SMTP tidak digunakan." />
      <div className="mt-6 grid gap-5 xl:grid-cols-2">
        <article className="rounded-2xl border border-slate-200 p-5"><h3 className="font-serif text-xl">Google Gmail</h3><NumberedSteps items={[
          "Di Google Cloud aktifkan Gmail API dan lengkapi OAuth consent screen.",
          "Create Credentials → OAuth client ID → Web application.",
          "Salin exact Google Redirect URI dari Settings → Notifications · Email → Provider Setup ke Authorized redirect URIs.",
          "Masukkan Client ID dan Client Secret di Provider Setup lalu Save Configuration. Scope aplikasi hanya openid, email, dan gmail.send.",
          "Buka Accounts → Connect Email Account → Google Gmail, selesaikan consent, jadikan default bila perlu, lalu Send Test Email.",
        ]}/><a href="https://developers.google.com/workspace/gmail/api/auth/web-server" target="_blank" rel="noreferrer" className="mt-4 inline-flex items-center gap-1 text-xs font-bold text-petrol">Google server-side OAuth guide <ExternalLink size={12}/></a></article>
        <article className="rounded-2xl border border-slate-200 p-5"><h3 className="font-serif text-xl">Microsoft Outlook / Exchange</h3><NumberedSteps items={[
          "Di Microsoft Entra admin center buka App registrations → New registration dan pilih account type yang sesuai organisasi.",
          "Authentication → Add a platform → Web, lalu masukkan exact Microsoft Redirect URI dari Provider Setup.",
          "Certificates & secrets → New client secret; API permissions → Microsoft Graph → Delegated → User.Read dan Mail.Send.",
          "Masukkan Application (client) ID, client secret, serta tenant. Single-tenant harus memakai Tenant ID/domain, bukan common.",
          "Save Configuration, lalu Accounts → Connect Microsoft, consent, dan Send Test Email.",
        ]}/><a href="https://learn.microsoft.com/en-us/graph/auth-register-app-v2" target="_blank" rel="noreferrer" className="mt-4 inline-flex items-center gap-1 text-xs font-bold text-petrol">Microsoft app registration guide <ExternalLink size={12}/></a></article>
      </div>
      <div className="mt-5 rounded-xl border border-blue-200 bg-blue-50 p-5 text-xs leading-6 text-blue-950"><strong>Urutan aktivasi:</strong> Provider Setup → Accounts → Recipients → Groups opsional → Alert Rules → General: Enable Email Channel → Notification Logs. Rule tanpa sender/recipient atau channel yang masih disabled tidak mengirim email. Pastikan <code>APP_BASE_URL</code>, <code>EMAIL_TOKEN_ENCRYPTION_KEY</code>, dan HTTPS redirect URI stabil pada production.</div>
    </section>

    <section id="page-guide" className="mt-8 scroll-mt-24">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <SectionTitle eyebrow="05 · Page reference" title="Fungsi page dan cara membaca card" description="Gunakan pencarian untuk menemukan istilah card, metric, atau workflow. Definisi mengikuti kontrak API yang dipakai UI." />
        <label className="relative block w-full md:w-80"><span className="sr-only">Cari dokumentasi page</span><Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={15}/><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Cari page, card, atau metric…" className="h-11 w-full border border-slate-300 py-2 pl-10 pr-3 text-xs"/></label>
      </div>
      <div className="mt-5 space-y-4">{filteredGuides.map((guide) => <article id={guide.id} key={guide.id} className="panel scroll-mt-24 overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-slate-200 p-5 md:flex-row md:items-center md:justify-between"><div><div className="eyebrow">Page guide</div><h3 className="mt-1 font-serif text-xl">{guide.name}</h3><p className="mt-2 max-w-4xl text-xs leading-5 text-slate-500">{guide.purpose}</p></div><Link href={guide.href} className="inline-flex shrink-0 items-center gap-1 text-xs font-bold text-petrol">Buka page <ChevronRight size={13}/></Link></div>
        <div className="grid gap-px bg-slate-200 sm:grid-cols-2 xl:grid-cols-3">{guide.cards.map((card) => <div key={`${guide.id}-${card.name}`} className="bg-white p-5"><div className="text-[10px] font-black uppercase tracking-wider text-slate-400">{card.name}</div><p className="mt-2 text-xs leading-5 text-slate-600">{card.meaning}</p></div>)}</div>
        {guide.practice && <div className="border-t border-emerald-100 bg-emerald-50 px-5 py-3 text-xs leading-5 text-emerald-900"><strong>Cara pakai:</strong> {guide.practice}</div>}
      </article>)}{filteredGuides.length === 0 && <div className="panel p-12 text-center text-sm text-slate-400">Tidak ada dokumentasi yang cocok dengan “{query}”.</div>}</div>
    </section>

    <section className="panel mt-5 p-5 md:p-7"><div className="flex items-start gap-3"><span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-emerald-50 text-emerald-700"><BookOpenCheck size={20}/></span><div><h2 className="font-serif text-xl">Aturan interpretasi singkat</h2><ul className="mt-3 space-y-2 text-xs leading-5 text-slate-600"><li>• Signal adalah satu artikel/post; incident adalah satu kejadian yang dapat memiliki banyak signal.</li><li>• TikTok adalah early evidence, News adalah koroborasi; keduanya tetap harus diverifikasi operator untuk keputusan kritis.</li><li>• Nearest TBBM adalah kedekatan geospasial, Serving TBBM adalah mapping operasional, dan exposure tidak sama dengan causation.</li><li>• Filter selalu mengubah populasi yang dihitung. Bandingkan angka hanya bila rentang tanggal dan filter sama.</li><li>• Status HEALTHY adalah health teknis terakhir; lihat Provider Health dan Logs untuk koneksi eksternal.</li></ul></div></div></section>
  </div>;
}
