import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

type Book = {
  id: string;
  title: string;
  author: string;
  original_filename: string;
  file_size: number;
  status: string;
  created_at: string;
};

type User = { username: string };

type NaatVersion = {
  id?: string;
  language: string;
  format: 'transliteration' | 'translation';
  text: string;
  status: 'draft' | 'reviewed' | 'approved' | 'published';
  script_code?: string;
  source_id?: string | null;
};

type NaatSource = {
  id: string;
  naat_id: string;
  language: string;
  script_code: string;
  source_format: 'urdu_script' | 'roman_urdu' | 'other';
  text: string;
  status: 'draft' | 'reviewed' | 'approved' | 'published';
  created_at?: string;
  updated_at?: string;
};

type Collection = {
  id: string;
  title: string;
  author: string;
  description: string;
  cover_image?: string | null;
  naat_count: number;
  created_at: string;
  updated_at: string;
};

type Naat = {
  id: string;
  title: string;
  poet?: string;
  book_name?: string;
  page_number?: number | null;
  collection_id?: string | null;
  source_language: string;
  original_text: string;
  source_format: string;
  status: string;
  created_at?: string;
  updated_at?: string;
};

type TransliterationPage = {
  page_number: number;
  source_urdu: string;
  roman_urdu: string;
  status: 'draft' | 'reviewed' | 'approved';
  processing_status?: string;
};

type BookInspection = {
  book: Book;
  inspection: {
    page_count: number;
    pages_with_selectable_text: number;
    pages_likely_scanned: number;
    text_extraction_available: boolean;
    pages: Array<{
      page_number: number;
      width_pt: number;
      height_pt: number;
      text_characters: number;
      has_selectable_text: boolean;
      text_sample: string;
    }>;
  };
};

async function api(path: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(`/api/v1${path}`, {
    ...options,
    credentials: 'same-origin',
    headers,
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || `Request failed (${response.status})`);
  }

  return response.json();
}

function Icon({ name, size = 20 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
    grid: <><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></>,
    book: <><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"/></>,
    poetry: <><path d="M8 6h13M8 12h13M8 18h13"/><path d="M3 6h.01M3 12h.01M3 18h.01"/></>,
    language: <><path d="m5 8 6 6"/><path d="m4 14 6-6 2-3"/><path d="M2 5h12"/><path d="M7 2v3"/><path d="M14 22l5-11 5 11"/><path d="M16 18h6"/></>,
    check: <><path d="m5 12 4 4L19 6"/></>,
    upload: <><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5"/><path d="M12 3v12"/></>,
    search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>,
    logout: <><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/></>,
    arrow: <><path d="M7 17 17 7M7 7h10v10"/></>,
    file: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M8 13h8M8 17h8"/></>,
    menu: <><path d="M4 6h16M4 12h16M4 18h16"/></>,
    refresh: <><path d="M20 7v5h-5"/><path d="M4 17v-5h5"/><path d="M5.6 9a7 7 0 0 1 11.6-2L20 12M4 12l2.8 5a7 7 0 0 0 11.6-2"/></>,
    spark: <><path d="m12 3 1.9 5.8L20 11l-6.1 2.2L12 19l-1.9-5.8L4 11l6.1-2.2L12 3Z"/><path d="m19 14 1.2 2.8L23 18l-2.8 1.2L19 22l-1.2-2.8L15 18l2.8-1.2L19 14Z"/></>,
  };

  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"
      strokeLinejoin="round" aria-hidden="true">
      {paths[name] || paths.file}
    </svg>
  );
}

const navItems = [
  { id: 'lyrics', label: 'Naat Library', icon: 'poetry' },
  { id: 'collections', label: 'Collections', icon: 'book' },
  { id: 'books', label: 'Book Library', icon: 'book' },
];

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [books, setBooks] = useState<Book[]>([]);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [collectionTitle, setCollectionTitle] = useState('');
  const [collectionAuthor, setCollectionAuthor] = useState('');
  const [collectionDescription, setCollectionDescription] = useState('');
  const [editingCollectionId, setEditingCollectionId] = useState('');
  const [collectionCover, setCollectionCover] = useState<File | null>(null);
  const [collectionBusy, setCollectionBusy] = useState(false);
  const [page, setPage] = useState('lyrics');
  const [mobileMenu, setMobileMenu] = useState(false);
  const [title, setTitle] = useState('');
  const [author, setAuthor] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [search, setSearch] = useState('');
  const [inspection, setInspection] = useState<BookInspection | null>(null);
  const [inspectingId, setInspectingId] = useState('');
  const [transBookId, setTransBookId] = useState('');
  const [transStart, setTransStart] = useState('21');
  const [transEnd, setTransEnd] = useState('30');
  const [transPages, setTransPages] = useState<TransliterationPage[]>([]);
  const [transIndex, setTransIndex] = useState(0);
  const [transUrdu, setTransUrdu] = useState('');
  const [transRoman, setTransRoman] = useState('');
  const [transStatus, setTransStatus] = useState<'draft' | 'reviewed' | 'approved'>('draft');
  const [transBusy, setTransBusy] = useState(false);

  const [naats, setNaats] = useState<Naat[]>([]);
  const [naatLibrarySearch, setNaatLibrarySearch] = useState('');
  const [naatLibraryPage, setNaatLibraryPage] = useState(1);
  const [naatLibraryPageSize, setNaatLibraryPageSize] = useState(5);
  const [lyricsId, setLyricsId] = useState('');
  const [lyricsTitle, setLyricsTitle] = useState('');
  const [lyricsPoet, setLyricsPoet] = useState('');
  const [lyricsBookName, setLyricsBookName] = useState('');
  const [lyricsPageNumber, setLyricsPageNumber] = useState('');
  const [lyricsSourceLanguage, setLyricsSourceLanguage] = useState('Urdu');
  const [lyricsSourceFormat, setLyricsSourceFormat] = useState('urdu_script');
  const [lyricsOriginalText, setLyricsOriginalText] = useState('');
  const [lyricsVersions, setLyricsVersions] = useState<NaatVersion[]>([]);
  const [lyricsSources, setLyricsSources] = useState<NaatSource[]>([]);
  const [selectedSourceId, setSelectedSourceId] = useState('');
  const [sourceLanguage, setSourceLanguage] = useState('Urdu');
  const [sourceScriptCode, setSourceScriptCode] = useState('ur-Arab');
  const [sourceFormat, setSourceFormat] = useState<'urdu_script' | 'roman_urdu' | 'other'>('urdu_script');
  const [sourceText, setSourceText] = useState('');
  const [lyricsRomanText, setLyricsRomanText] = useState('');
  const [lyricsKannadaText, setLyricsKannadaText] = useState('');
  const [lyricsBusy, setLyricsBusy] = useState(false);
  const [lyricsIssues, setLyricsIssues] = useState<string[]>([]);

  async function loadBooks() {
    const data = await api('/books');
    setBooks(data.books || []);
  }

  async function loadCollections() {
    const data = await api('/collections');
    setCollections(data.collections || []);
  }

  useEffect(() => {
    api('/auth/me')
      .then((data) => setUser(data))
      .catch(() => setUser(null))
      .finally(() => setChecking(false));
  }, []);

  useEffect(() => {
    if (user) {
      loadBooks().catch((err) => setError(err.message));
      loadCollections().catch((err) => setError(err.message));
    }
  }, [user]);

  async function login(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const data = await api('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      });
      setUser(data);
      setPassword('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign in failed');
    } finally {
      setBusy(false);
    }
  }

  async function inspectBook(book: Book) {
    setError('');
    setNotice('');
    setInspectingId(book.id);
    setInspection(null);
    setPage('book-details');
    try {
      const data = await api(`/books/${encodeURIComponent(book.id)}/inspect`);
      setInspection(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'PDF inspection failed');
    } finally {
      setInspectingId('');
    }
  }


  async function loadTransPages() {
    if (!transBookId) {
      setError('Select a book first.');
      return;
    }
    const start = Number(transStart);
    const end = Number(transEnd);
    if (!Number.isInteger(start) || !Number.isInteger(end) ||
        start < 1 || end < start || end - start > 99) {
      setError('Choose a valid page range of up to 100 pages.');
      return;
    }

    console.info('[Naatify transliteration] Loading pages', { bookId: transBookId, start, end });
    setTransBusy(true);
    setError('');
    setNotice('Loading pages…');
    try {
      const data = await api(
        `/transliterations?book_id=${encodeURIComponent(transBookId)}&start_page=${start}&end_page=${end}`
      );
      const pages: TransliterationPage[] = data.pages || [];
      console.info('[Naatify transliteration] Pages received', {
        count: pages.length,
        pageNumbers: pages.map((p) => p.page_number),
        sourceCharacters: pages.reduce((n, p) => n + (p.source_urdu || '').length, 0),
        romanCharacters: pages.reduce((n, p) => n + (p.roman_urdu || '').length, 0),
      });
      setTransPages(pages);
      setTransIndex(0);
      setTransUrdu(pages[0]?.source_urdu || '');
      setTransRoman(pages[0]?.roman_urdu || '');
      setTransStatus(pages[0]?.status || 'draft');
      setNotice(pages.length
        ? `Loaded ${pages.length} page(s), ${start}–${end}. Select a page and enter Urdu text.`
        : 'No pages returned for this range.');
    } catch (err) {
      console.error('[Naatify transliteration] Load pages failed', err);
      setError(err instanceof Error ? err.message : 'Unable to load pages');
    } finally {
      setTransBusy(false);
    }
  }

  async function extractTransPages() {
    if (!transBookId) {
      setError('Select a book first.');
      return;
    }

    const start = Number(transStart);
    const end = Number(transEnd);
    if (!Number.isInteger(start) || !Number.isInteger(end) ||
        start < 1 || end < start || end - start > 99) {
      setError('Choose a valid page range of up to 100 pages.');
      return;
    }

    setTransBusy(true);
    setError('');
    setNotice(`Extracting PDF pages ${start}–${end}. OCR may take some time…`);

    try {
      let totalCharacters = 0;
      let pagesProcessed = 0;

      for (let chunkStart = start; chunkStart <= end; chunkStart += 20) {
        const limit = Math.min(20, end - chunkStart + 1);
        const result = await api(
          `/books/${encodeURIComponent(transBookId)}/extract?start_page=${chunkStart}&limit=${limit}`,
          { method: 'POST' }
        );
        pagesProcessed += (result.pages || []).length;
        totalCharacters += (result.pages || []).reduce(
          (sum: number, page: { text_characters?: number }) =>
            sum + (page.text_characters || 0), 0
        );
        setNotice(`Extracted ${pagesProcessed} page(s) so far…`);
      }

      const data = await api(
        `/transliterations?book_id=${encodeURIComponent(transBookId)}&start_page=${start}&end_page=${end}`
      );
      const pages: TransliterationPage[] = data.pages || [];
      setTransPages(pages);
      setTransIndex(0);
      setTransUrdu(pages[0]?.source_urdu || '');
      setTransRoman(pages[0]?.roman_urdu || '');
      setTransStatus(pages[0]?.status || 'draft');
      setNotice(
        `Extraction finished: ${pagesProcessed} page(s), ${totalCharacters} detected text characters. Review OCR carefully before generating or approving Roman Urdu.`
      );
    } catch (err) {
      console.error('[Naatify transliteration] PDF extraction failed', err);
      setError(err instanceof Error ? err.message : 'PDF extraction failed');
    } finally {
      setTransBusy(false);
    }
  }

  function selectTransPage(index: number) {
    const item = transPages[index];
    if (!item) {
      console.warn('[Naatify transliteration] Page selection index missing', { index, count: transPages.length });
      return;
    }
    console.info('[Naatify transliteration] Page selected', {
      index, pageNumber: item.page_number,
      sourceCharacters: (item.source_urdu || '').length,
      romanCharacters: (item.roman_urdu || '').length,
      status: item.status,
    });
    setTransIndex(index);
    setTransUrdu(item.source_urdu || '');
    setTransRoman(item.roman_urdu || '');
    setTransStatus(item.status || 'draft');
    setError('');
    setNotice('');
  }

  async function generateTransliteration() {
    const item = transPages[transIndex];
    if (!item || !transUrdu.trim()) {
      setError('Enter the Urdu text before generating Roman Urdu.');
      return;
    }
    if (transStatus === 'approved') {
      setError('This page is approved. Reopen it for review before regenerating.');
      return;
    }
    console.info('[Naatify transliteration] Generate clicked', {
      bookId: transBookId, pageNumber: item.page_number,
      sourceCharacters: transUrdu.length, status: transStatus,
    });
    setTransBusy(true);
    setError('');
    setNotice('Generating Roman Urdu…');
    try {
      const result = await api('/transliterations/generate', {
        method: 'POST',
        body: JSON.stringify({
          book_id: transBookId,
          page_number: item.page_number,
          source_urdu: transUrdu,
          roman_urdu: transRoman,
          status: transStatus,
        }),
      });
      console.info('[Naatify transliteration] Generate succeeded', {
        pageNumber: result.page_number,
        romanCharacters: (result.roman_urdu || '').length,
        reviewStatus: result.review_status,
      });
      setTransRoman(result.roman_urdu || '');
      setNotice(`Generated Roman Urdu (${(result.roman_urdu || '').length} characters). Review it before saving.`);
    } catch (err) {
      console.error('[Naatify transliteration] Generate failed', err);
      setError(err instanceof Error ? err.message : 'Transliteration failed');
    } finally {
      setTransBusy(false);
    }
  }

  async function saveTransliteration(status: 'draft' | 'reviewed' | 'approved') {
    const item = transPages[transIndex];
    if (!item || !transUrdu.trim() || !transRoman.trim()) {
      setError('Both Urdu and Roman Urdu are required before saving.');
      return;
    }
    if (status === 'approved' &&
        !window.confirm(`Approve page ${item.page_number}? Please ensure both texts have been checked.`)) {
      return;
    }
    console.info('[Naatify transliteration] Save clicked', {
      bookId: transBookId, pageNumber: item.page_number, targetStatus: status,
      sourceCharacters: transUrdu.length, romanCharacters: transRoman.length,
    });
    setTransBusy(true);
    setError('');
    setNotice(`Saving page ${item.page_number}…`);
    try {
      const result = await api('/transliterations', {
        method: 'PUT',
        body: JSON.stringify({
          book_id: transBookId,
          page_number: item.page_number,
          source_urdu: transUrdu,
          roman_urdu: transRoman,
          status,
        }),
      });
      const next = [...transPages];
      next[transIndex] = {
        ...item, source_urdu: transUrdu, roman_urdu: transRoman, status: result.status,
      };
      setTransPages(next);
      setTransStatus(result.status);
      console.info('[Naatify transliteration] Save succeeded', {
        pageNumber: result.page_number, status: result.status,
      });
      setNotice(`Page ${item.page_number} saved as ${result.status}.`);
    } catch (err) {
      console.error('[Naatify transliteration] Save failed', err);
      setError(err instanceof Error ? err.message : 'Unable to save page');
    } finally {
      setTransBusy(false);
    }
  }

  async function exportTransliterations() {
    if (!transBookId) {
      setError('Select a book first.');
      return;
    }
    setTransBusy(true);
    setError('');
    try {
      const response = await fetch(
        `/api/v1/transliterations/export?book_id=${encodeURIComponent(transBookId)}`,
        { credentials: 'same-origin' }
      );
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || `Export failed (${response.status})`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `naatify-approved-${transBookId}.json`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setNotice('Approved-content JSON export downloaded.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed');
    } finally {
      setTransBusy(false);
    }
  }

  function startNewNaat() {
    setLyricsId('');
    setLyricsTitle('');
    setLyricsPoet('');
    setLyricsBookName('');
    setLyricsPageNumber('');
    setLyricsSourceLanguage('Urdu');
    setLyricsSourceFormat('urdu_script');
    setLyricsOriginalText('');
    setLyricsVersions([]);
    setLyricsSources([]);
    setSelectedSourceId('');
    setSourceLanguage('Urdu');
    setSourceScriptCode('ur-Arab');
    setSourceFormat('urdu_script');
    setSourceText('');
    setLyricsRomanText('');
    setLyricsKannadaText('');
    setLyricsIssues([]);
    setError('');
    setNotice('Ready to create a new naat. Previously saved naats are unchanged.');
  }

  async function loadNaats() {
    const data = await api('/naats');
    setNaats(data.naats || []);
  }

  async function deleteNaat(naat: Naat) {
    if (!window.confirm(
      `Delete "${naat.title}"${naat.book_name ? ` from ${naat.book_name}` : ''}? This also deletes its saved language versions and revision history. This cannot be undone.`
    )) return;

    setLyricsBusy(true);
    setError('');
    setNotice('');
    try {
      await api(`/naats/${encodeURIComponent(naat.id)}`, { method: 'DELETE' });
      if (lyricsId === naat.id) startNewNaat();
      await loadNaats();
      setNotice(`Deleted "${naat.title}".`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not delete the naat.');
    } finally {
      setLyricsBusy(false);
    }
  }

  async function createNaat() {
    if (!lyricsTitle.trim() || !lyricsPoet.trim() || !lyricsBookName.trim() || !lyricsOriginalText.trim()) {
      setError('Enter the title, author, book name and original lyrics first. Use Anonymous or Unknown if not known.');
      return;
    }
    setLyricsBusy(true);
    setError('');
    setNotice('');
    try {
      const data = await api('/naats', {
        method: 'POST',
        body: JSON.stringify({
          title: lyricsTitle.trim(),
          poet: lyricsPoet.trim(),
          book_name: lyricsBookName.trim(),
          page_number: lyricsPageNumber.trim() ? Number(lyricsPageNumber) : null,
          source_language: lyricsSourceLanguage,
          source_format: lyricsSourceFormat,
          original_text: lyricsOriginalText
        })
      });
      const created = data.naat || data;
      await loadNaats();
      await openNaat(created.id);
      setNotice(
        created.page_number
          ? `Lyrics draft saved — page ${created.page_number}.`
          : 'Lyrics draft created and saved.'
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create lyrics draft.');
    } finally {
      setLyricsBusy(false);
    }
  }

  async function openNaat(id: string) {
    setLyricsBusy(true);
    setError('');
    setNotice('');
    try {
      const data = await api(`/naats/${encodeURIComponent(id)}`);
      const naat = data.naat || data;
      setLyricsId(naat.id);
      setLyricsTitle(naat.title || '');
      setLyricsPoet(naat.poet || '');
      setLyricsBookName(naat.book_name || '');
      setLyricsPageNumber(naat.page_number == null ? '' : String(naat.page_number));
      setLyricsSourceLanguage(naat.source_language || 'Urdu');
      setLyricsSourceFormat(naat.source_format || 'urdu_script');
      setLyricsOriginalText(naat.original_text || '');
      const versions: NaatVersion[] = data.versions || [];
      setLyricsVersions(versions);
      const sources: NaatSource[] = data.sources || [];
      setLyricsSources(sources);
      const firstSource = sources[0];
      setSelectedSourceId(firstSource?.id || '');
      setSourceLanguage(firstSource?.language || 'Urdu');
      setSourceScriptCode(firstSource?.script_code || 'ur-Arab');
      setSourceFormat(firstSource?.source_format || 'urdu_script');
      setSourceText(firstSource?.text || '');
      setLyricsRomanText(
        versions.find(v => v.language === 'Roman Urdu' && v.format === 'transliteration')?.text || ''
      );
      setLyricsKannadaText(
        versions.find(v => v.language === 'Kannada' && v.format === 'transliteration')?.text || ''
      );
      setLyricsIssues([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load lyrics.');
    } finally {
      setLyricsBusy(false);
    }
  }

  async function saveLyricsSource() {
    if (!lyricsTitle.trim() || !lyricsPoet.trim() || !lyricsBookName.trim()) {
      setError('Title, author and book name are required. Use Anonymous or Unknown if not known.');
      return;
    }
    if (!lyricsId) {
      setError('Create a lyrics draft first.');
      return;
    }
    setLyricsBusy(true);
    setError('');
    try {
      await api(`/naats/${encodeURIComponent(lyricsId)}`, {
        method: 'PUT',
        body: JSON.stringify({
          title: lyricsTitle.trim(),
          poet: lyricsPoet.trim(),
          book_name: lyricsBookName.trim(),
          page_number: lyricsPageNumber.trim() ? Number(lyricsPageNumber) : null,
          source_language: lyricsSourceLanguage,
          source_format: lyricsSourceFormat,
          original_text: lyricsOriginalText
        })
      });
      await loadNaats();
      setNotice('Original lyrics saved.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save original lyrics.');
    } finally {
      setLyricsBusy(false);
    }
  }

  function selectLyricsSource(sourceId: string) {
    const source = lyricsSources.find(item => item.id === sourceId);
    setSelectedSourceId(sourceId);
    setSourceLanguage(source?.language || 'Urdu');
    setSourceScriptCode(source?.script_code || 'ur-Arab');
    setSourceFormat(source?.source_format || 'urdu_script');
    setSourceText(source?.text || '');
  }

  async function saveLyricsSourceRecord(
    status: 'draft' | 'reviewed' | 'approved' = 'draft'
  ) {
    if (!lyricsId) {
      setError('Create the Naat before adding additional sources.');
      return;
    }
    if (!sourceLanguage.trim() || !sourceScriptCode.trim() || !sourceText.trim()) {
      setError('Enter the source language, script code and original text.');
      return;
    }

    setLyricsBusy(true);
    setError('');
    setNotice('');

    try {
      const payload = {
        language: sourceLanguage.trim(),
        script_code: sourceScriptCode.trim(),
        source_format: sourceFormat,
        text: sourceText,
        status,
      };

      const path = `/naats/${encodeURIComponent(lyricsId)}/sources`;
      const saved = selectedSourceId
        ? await api(`${path}/${encodeURIComponent(selectedSourceId)}`, {
            method: 'PUT',
            body: JSON.stringify(payload),
          })
        : await api(path, {
            method: 'POST',
            body: JSON.stringify(payload),
          });

      const result = await api(path);
      const sources: NaatSource[] = result.sources || [];
      setLyricsSources(sources);

      const current = sources.find(item => item.id === saved.id);
      if (current) selectLyricsSource(current.id);

      setNotice(
        status === 'approved' ? 'Source approved.' :
        status === 'reviewed' ? 'Source marked as reviewed.' :
        selectedSourceId ? 'Source saved as draft. Previous text is retained in revision history.' :
        'New source added as a draft.'
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save source.');
    } finally {
      setLyricsBusy(false);
    }
  }

  async function publishLyricsSource() {
    if (!lyricsId || !selectedSourceId) {
      setError('Select a saved source before publishing.');
      return;
    }

    const selected = lyricsSources.find(item => item.id === selectedSourceId);
    if (!selected || selected.status !== 'approved') {
      setError('Approve this source before publishing.');
      return;
    }

    if (!window.confirm('Publish this Urdu source? It will become available in the public API.')) {
      return;
    }

    setLyricsBusy(true);
    setError('');
    setNotice('');

    try {
      await api(
        `/naats/${encodeURIComponent(lyricsId)}/sources/${encodeURIComponent(selectedSourceId)}/publish`,
        { method: 'POST' }
      );

      const result = await api(`/naats/${encodeURIComponent(lyricsId)}/sources`);
      const sources: NaatSource[] = result.sources || [];
      setLyricsSources(sources);
      const current = sources.find(item => item.id === selectedSourceId);
      if (current) selectLyricsSource(current.id);

      setNotice('Source published successfully.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not publish source.');
    } finally {
      setLyricsBusy(false);
    }
  }

  async function generateLyricsRomanUrdu() {
    if (!lyricsOriginalText.trim() || !lyricsId) {
      setError('Enter the original lyrics and create the draft first.');
      return;
    }
    if (lyricsSourceFormat === 'roman_urdu') {
      setLyricsRomanText(lyricsOriginalText);
      setNotice('Roman Urdu source copied to the Roman Urdu output.');
      setError('');
      return;
    }
    if (lyricsSourceFormat !== 'urdu_script' || lyricsSourceLanguage !== 'Urdu') {
      setError('Use Urdu script or Roman Urdu as the source.');
      return;
    }

    setLyricsBusy(true);
    setError('');
    setNotice('Generating Roman Urdu…');
    try {
      const result = await api('/transliterate', {
        method: 'POST',
        body: JSON.stringify({ text: lyricsOriginalText })
      });
      const generated = result.roman_urdu || '';
      if (!generated.trim()) throw new Error('The transliteration engine returned empty text.');
      setLyricsRomanText(generated);
      setNotice('Roman Urdu generated. Review it before saving.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Roman Urdu generation failed.');
    } finally {
      setLyricsBusy(false);
    }
  }

  async function generateLyricsKannada() {
    if (!lyricsId) {
      setError('Create or open a lyrics draft first.');
      return;
    }

    const savedRoman = lyricsVersions.find(
      v => v.language === 'Roman Urdu' && v.format === 'transliteration'
    );

    if (!savedRoman || !savedRoman.text.trim()) {
      setError('Save a non-empty Roman Urdu version before generating Kannada.');
      return;
    }

    const currentRoman = lyricsSourceFormat === 'roman_urdu'
      ? lyricsOriginalText
      : lyricsRomanText;

    if (currentRoman !== savedRoman.text) {
      setError('Roman Urdu has unsaved changes. Save it before generating Kannada.');
      return;
    }

    setLyricsBusy(true);
    setError('');
    setNotice('');

    try {
      setNotice('Queuing Kannada conversion…');

      const job = await api(
        `/naats/${encodeURIComponent(lyricsId)}/conversion-jobs`,
        { method: 'POST' }
      );

      if (!job.id) {
        throw new Error('The backend did not return a conversion job ID.');
      }

      setNotice('Kannada conversion queued. Waiting for the result…');

      for (let attempt = 0; attempt < 150; attempt++) {
        const result = await api(
          `/conversion-jobs/${encodeURIComponent(job.id)}`
        );

        if (result.status === 'completed') {
          const data = await api(`/naats/${encodeURIComponent(lyricsId)}`);
          const versions: NaatVersion[] = data.versions || [];

          setLyricsVersions(versions);

          const kannada = versions.find(
            v => v.language === 'Kannada' && v.format === 'transliteration'
          );

          setLyricsKannadaText(kannada?.text || result.generated_text || '');
          setNotice('Kannada generated and saved as a draft. Review it before approval.');
          return;
        }

        if (result.status === 'failed') {
          throw new Error(result.error_message || 'Kannada conversion failed.');
        }

        if (result.status === 'cancelled') {
          throw new Error('Kannada conversion was cancelled.');
        }

        await new Promise(resolve => window.setTimeout(resolve, 2000));
      }

      setNotice(
        'Kannada conversion is still running. Reopen this Naat later to check the draft.'
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Kannada generation failed.');
    } finally {
      setLyricsBusy(false);
    }
  }

  async function saveLyricsOutput(
    language: 'Roman Urdu' | 'Kannada',
    text: string,
    status: 'draft' | 'reviewed' | 'approved' = 'draft'
  ) {
    if (!lyricsId || !text.trim()) {
      setError(`Create or open a draft and enter the ${language} text first.`);
      return;
    }
    if (status === 'approved' &&
        !window.confirm(`Approve the ${language} version? Please check the text first.`)) return;

    setLyricsBusy(true);
    setError('');
    try {
      await api(`/naats/${encodeURIComponent(lyricsId)}/versions`, {
        method: 'PUT',
        body: JSON.stringify({ language, format: 'transliteration', text, status })
      });
      const data = await api(`/naats/${encodeURIComponent(lyricsId)}`);
      setLyricsVersions(data.versions || []);
      setNotice(`${language} saved as ${status}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : `Could not save ${language}.`);
    } finally {
      setLyricsBusy(false);
    }
  }

  async function validateLyrics() {
    if (!lyricsId) {
      setError('Create or open a lyrics draft first.');
      return;
    }
    setLyricsBusy(true);
    setError('');
    try {
      const result = await api(`/naats/${encodeURIComponent(lyricsId)}/validate`, {
        method: 'POST'
      });
      setLyricsIssues(result.issues || []);
      setNotice(result.valid ? 'Validation passed.' : 'Validation found items to review.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Validation failed.');
    } finally {
      setLyricsBusy(false);
    }
  }

  async function publishLyrics() {
    if (!lyricsId || !window.confirm('Publish this naat and its approved language versions?')) return;
    setLyricsBusy(true);
    setError('');
    try {
      await api(`/naats/${encodeURIComponent(lyricsId)}/publish`, { method: 'POST' });
      await openNaat(lyricsId);
      await loadNaats();
      setNotice('Naat published.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Publishing failed. Check that all versions are approved.');
    } finally {
      setLyricsBusy(false);
    }
  }

  function createNaatFromBookPage(book: Book, pageNumber: number) {
    startNewNaat();
    setLyricsTitle('');
    setLyricsPoet(book.author || '');
    setLyricsBookName(book.title);
    setLyricsPageNumber(String(pageNumber));
    setLyricsSourceLanguage('Urdu');
    setLyricsSourceFormat('urdu_script');
    setLyricsOriginalText('');
    setPage('lyrics');
    setNotice(`Book source selected: ${book.title}, page ${pageNumber}. Enter the original Urdu lyrics and save the naat.`);
    setError('');
  }

  function lyricsStudio() {
    const filteredLibraryNaats = [...naats]
      .filter(n => [n.title, n.poet || '', n.book_name || '']
        .some(value => value.toLowerCase().includes(naatLibrarySearch.trim().toLowerCase())))
      .sort((a, b) =>
        (a.poet || '').localeCompare(b.poet || '') ||
        (a.book_name || '').localeCompare(b.book_name || '') ||
        (a.page_number ?? Number.MAX_SAFE_INTEGER) - (b.page_number ?? Number.MAX_SAFE_INTEGER) ||
        a.title.localeCompare(b.title));

    const totalLibraryPages = Math.max(1, Math.ceil(filteredLibraryNaats.length / naatLibraryPageSize));
    const currentLibraryPage = Math.min(naatLibraryPage, totalLibraryPages);
    const pagedLibraryNaats = filteredLibraryNaats.slice(
      (currentLibraryPage - 1) * naatLibraryPageSize,
      currentLibraryPage * naatLibraryPageSize
    );

    return (
      <section className="panel transliteration-workspace">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">LYRICS MANAGEMENT</span>
            <h2>Lyrics Studio</h2>
          </div>
          <div className="transliteration-actions">
            <button className="primary-button" onClick={startNewNaat} disabled={lyricsBusy}>
              + New Naat
            </button>
            <button className="subtle-button" onClick={() => loadNaats().catch(err => setError(err.message))}>
              <Icon name="refresh" size={16} /> Refresh
            </button>
          </div>
        </div>
        <p className="muted">
          Create a naat from pasted lyrics, maintain editable language versions,
          and review each version before publishing. Transliteration preserves the
          words in another script; translation conveys the meaning in another language.
        </p>

        <div className="divider" />
        <h3>{lyricsId ? 'Edit Saved Naat' : 'Create New Naat'}</h3>
        <div className="transliteration-controls naat-meta-controls">
          <label>Saved naats
            <select value={lyricsId} onChange={e => e.target.value ? openNaat(e.target.value) : startNewNaat()}>
              <option value="">+ New naat</option>
              {naats.map(n => <option key={n.id} value={n.id}>{n.title} — {n.status}</option>)}
            </select>
          </label>
          <label>Title
            <input value={lyricsTitle} onChange={e => setLyricsTitle(e.target.value)} placeholder="Naat title" />
          </label>
          <label>Poet / author <span className="required">*</span>
            <input value={lyricsPoet} onChange={e => setLyricsPoet(e.target.value)} placeholder="Author name (or Anonymous)" required maxLength={200} />
          </label>
          <label>Book name <span className="required">*</span>
            <input value={lyricsBookName} onChange={e => setLyricsBookName(e.target.value)} placeholder="Book or collection (or Unknown)" required maxLength={200} />
          </label>
          <label>Page number
            <input type="number" min="1" step="1" value={lyricsPageNumber}
              onChange={e => setLyricsPageNumber(e.target.value)} placeholder="Auto-assign if blank" />
          </label>
          <label>Source language
            <select
              value={lyricsSourceFormat === 'roman_urdu' ? 'Roman Urdu' : 'Urdu'}
              onChange={e => {
                const isRoman = e.target.value === 'Roman Urdu';
                setLyricsSourceLanguage(isRoman ? 'Roman Urdu' : 'Urdu');
                setLyricsSourceFormat(isRoman ? 'roman_urdu' : 'urdu_script');
              }}>
              <option value="Urdu">Urdu script</option>
              <option value="Roman Urdu">Roman Urdu</option>
            </select>
          </label>
          <label>Source format
            <select value={lyricsSourceFormat} onChange={e => setLyricsSourceFormat(e.target.value)}>
              <option value="urdu_script">Urdu script</option>
              <option value="roman_urdu">Roman Urdu</option>
              <option value="other">Other</option>
            </select>
          </label>
        </div>

        <div className="transliteration-editors original-lyrics-editor">
          <label>Original lyrics
            <textarea rows={12} value={lyricsOriginalText}
              onChange={e => setLyricsOriginalText(e.target.value)}
              placeholder="Paste the complete lyrics here. Keep stanza breaks and line breaks." />
          </label>
        </div>

        {lyricsId && <>
          <div className="divider" />
          <h3>Original Sources</h3>
          <p className="muted">
            Manage multiple original scripts and languages under this Naat.
            Each source is saved independently with revision history.
          </p>

          <div className="transliteration-controls source-controls">
            <label>Existing sources
              <select
                value={selectedSourceId}
                onChange={e => selectLyricsSource(e.target.value)}
              >
                <option value="">+ Add another source</option>
                {lyricsSources.map(source => (
                  <option key={source.id} value={source.id}>
                    {source.language} · {source.script_code} · {source.status}
                  </option>
                ))}
              </select>
            </label>

            <label>Source language
              <input
                value={sourceLanguage}
                onChange={e => setSourceLanguage(e.target.value)}
                placeholder="Urdu, Arabic, etc."
              />
            </label>

            <label>Script code
              <input
                value={sourceScriptCode}
                onChange={e => setSourceScriptCode(e.target.value)}
                placeholder="ur-Arab, ur-Latn, etc."
              />
            </label>

            <label>Source format
              <select
                value={sourceFormat}
                onChange={e => setSourceFormat(e.target.value as 'urdu_script' | 'roman_urdu' | 'other')}
              >
                <option value="urdu_script">Urdu / native script</option>
                <option value="roman_urdu">Roman Urdu</option>
                <option value="other">Other</option>
              </select>
            </label>
          </div>

          <label className="source-text-field">Source text
            <textarea
              rows={10}
              value={sourceText}
              onChange={e => setSourceText(e.target.value)}
              placeholder="Enter the complete original lyrics..."
            />
          </label>

          <div className="transliteration-actions">
            <button
              className="subtle-button"
              disabled={lyricsBusy || !sourceText.trim()}
              onClick={() => saveLyricsSourceRecord('draft')}
            >
              Save draft
            </button>
            <button
              className="subtle-button"
              disabled={lyricsBusy || !selectedSourceId || !sourceText.trim() ||
                lyricsSources.find(item => item.id === selectedSourceId)?.status === 'published'}
              onClick={() => saveLyricsSourceRecord('reviewed')}
            >
              Mark reviewed
            </button>
            <button
              className="primary-button"
              disabled={lyricsBusy || !selectedSourceId || !sourceText.trim() ||
                lyricsSources.find(item => item.id === selectedSourceId)?.status === 'published'}
              onClick={() => saveLyricsSourceRecord('approved')}
            >
              Approve source
            </button>
            <button
              className="primary-button"
              disabled={lyricsBusy ||
                lyricsSources.find(item => item.id === selectedSourceId)?.status !== 'approved'}
              onClick={publishLyricsSource}
            >
              Publish source
            </button>
            <button
              className="subtle-button"
              disabled={lyricsBusy}
              onClick={() => selectLyricsSource('')}
            >
              Clear / New source
            </button>
          </div>
        </>}

        <div className="transliteration-actions">
          {!lyricsId ? (
            <button className="primary-button" disabled={lyricsBusy} onClick={createNaat}>
              Create draft
            </button>
          ) : (
            <button className="primary-button" disabled={lyricsBusy} onClick={saveLyricsSource}>
              Update Naat
            </button>
          )}
        </div>

        {lyricsId && <>
          <div className="divider" />
          <h3>Roman Urdu and Kannada</h3>
          <p className="muted">
            Edit and save each output independently. Kannada is generated from Roman Urdu.
            Review spelling and pronunciation before approving either version.
          </p>

          <div className="transliteration-actions">
            <button className="subtle-button"
              disabled={lyricsBusy || !lyricsOriginalText.trim() || !lyricsId}
              onClick={generateLyricsRomanUrdu}>Generate Roman Urdu</button>
            <button className="subtle-button"
              disabled={lyricsBusy || !lyricsOriginalText.trim() || !lyricsId}
              onClick={generateLyricsKannada}>Generate Kannada</button>
          </div>

          <div className="transliteration-editors">
            <label>Roman Urdu
              <textarea rows={12} value={lyricsRomanText}
                onChange={e => setLyricsRomanText(e.target.value)}
                placeholder="Edit Roman Urdu here. Preserve stanza breaks." />
              <div className="transliteration-actions">
                <button className="primary-button" disabled={lyricsBusy}
                  onClick={() => saveLyricsOutput('Roman Urdu', lyricsRomanText, 'draft')}>Save Roman Urdu</button>
                <button className="subtle-button" disabled={lyricsBusy}
                  onClick={() => saveLyricsOutput('Roman Urdu', lyricsRomanText, 'reviewed')}>Mark reviewed</button>
                <button className="subtle-button" disabled={lyricsBusy}
                  onClick={() => saveLyricsOutput('Roman Urdu', lyricsRomanText, 'approved')}>Approve</button>
                <button className="subtle-button" disabled={!lyricsRomanText.trim()}
                  onClick={() => navigator.clipboard.writeText(lyricsRomanText)
                    .then(() => setNotice('Roman Urdu copied.'))
                    .catch(() => setError('Could not copy Roman Urdu.'))}>Copy</button>
              </div>
            </label>

            <label>Kannada
              <textarea rows={12} value={lyricsKannadaText}
                onChange={e => setLyricsKannadaText(e.target.value)}
                placeholder="Edit Kannada here. Preserve stanza breaks." />
              <div className="transliteration-actions">
                <button className="primary-button" disabled={lyricsBusy}
                  onClick={() => saveLyricsOutput('Kannada', lyricsKannadaText, 'draft')}>Save Kannada</button>
                <button className="subtle-button" disabled={lyricsBusy}
                  onClick={() => saveLyricsOutput('Kannada', lyricsKannadaText, 'reviewed')}>Mark reviewed</button>
                <button className="subtle-button" disabled={lyricsBusy}
                  onClick={() => saveLyricsOutput('Kannada', lyricsKannadaText, 'approved')}>Approve</button>
                <button className="subtle-button" disabled={!lyricsKannadaText.trim()}
                  onClick={() => navigator.clipboard.writeText(lyricsKannadaText)
                    .then(() => setNotice('Kannada copied.'))
                    .catch(() => setError('Could not copy Kannada.'))}>Copy</button>
              </div>
            </label>
          </div>

          <div className="transliteration-actions">
            <button className="subtle-button" disabled={lyricsBusy} onClick={validateLyrics}>Validate</button>
            <button className="subtle-button" disabled={lyricsBusy} onClick={publishLyrics}>Publish naat</button>
          </div>
          {lyricsIssues.length > 0 && <div className="alert" role="status">
            <strong>Validation results</strong>
            <ul>{lyricsIssues.map((issue, i) => <li key={i}>{issue}</li>)}</ul>
          </div>}
          <h3>Saved versions</h3>
          {lyricsVersions.length === 0 ? <p className="muted">No language versions saved yet.</p> :
            <div className="trans-page-strip">
              {lyricsVersions.map((v, i) => <button className="trans-page-button" key={`${v.language}-${v.format}-${i}`}
                onClick={() => {
                  if (v.language === 'Roman Urdu' && v.format === 'transliteration') {
                    setLyricsRomanText(v.text);
                  } else if (v.language === 'Kannada' && v.format === 'transliteration') {
                    setLyricsKannadaText(v.text);
                  }
                }}>
                <strong>{v.language}</strong><small>{v.format} · {v.status}</small>
              </button>)}
            </div>}
        </>}
        <div className="divider" />
        <div className="panel-heading">
          <div>
            <h3>Saved Naat Library</h3>
            <p className="muted">{naats.length} saved naat{naats.length === 1 ? '' : 's'}</p>
          </div>
        </div>
        <label>Search saved naats
          <input
            value={naatLibrarySearch}
            onChange={e => {
              setNaatLibrarySearch(e.target.value);
              setNaatLibraryPage(1);
            }}
            placeholder="Search title, author, or book"
          />
        </label>
        <label>Show per page
          <select
            value={naatLibraryPageSize}
            onChange={e => {
              setNaatLibraryPageSize(Number(e.target.value));
              setNaatLibraryPage(1);
            }}
          >
            {[1, 2, 3, 4, 5].map(size => (
              <option key={size} value={size}>{size} naat{size === 1 ? '' : 's'}</option>
            ))}
          </select>
        </label>
        <div className="naat-library-list">
          {Object.entries(
            pagedLibraryNaats.reduce<Record<string, Naat[]>>((groups, n) => {
              const author = (n.poet || '').trim() || 'Author not specified';
              const book = (n.book_name || '').trim() || 'Book not specified';
              const key = `${author}|||${book}`;
              (groups[key] ||= []).push(n);
              return groups;
            }, {})
          ).map(([key, group]) => {
            const [author, book] = key.split('|||');
            return (
              <details className="naat-book-group" key={key} open>
                <summary>
                  <strong>{book}</strong>
                  <span>{author} · {group.length} naat{group.length === 1 ? '' : 's'}</span>
                </summary>
                {group.map(n => (
                  <div className="naat-library-item" key={n.id}>
                    <div className="naat-library-details">
                      <strong>{n.title}</strong>
                      <span>Page {n.page_number ?? 'Not assigned'}</span>
                      <span>Status: {n.status}</span>
                    </div>
                    <div className="transliteration-actions">
                      <button className="primary-button" disabled={lyricsBusy}
                        onClick={() => openNaat(n.id)}>Edit</button>
                      <button className="subtle-button" disabled={lyricsBusy}
                        onClick={() => deleteNaat(n)}>Delete</button>
                    </div>
                  </div>
                ))}
              </details>
            );
          })}
          {naats.length === 0 && <p className="muted">No saved naats yet. Create your first draft below.</p>}
          {naats.length > 0 && filteredLibraryNaats.length === 0 &&
            <p className="muted">No naats match your search.</p>}
        </div>
        {filteredLibraryNaats.length > 0 && (
          <div className="naat-library-pagination">
            <span className="muted">
              Showing {(currentLibraryPage - 1) * naatLibraryPageSize + 1}–{Math.min(currentLibraryPage * naatLibraryPageSize, filteredLibraryNaats.length)} of {filteredLibraryNaats.length}
            </span>
            <div className="transliteration-actions">
              <button
                className="subtle-button"
                disabled={currentLibraryPage <= 1 || lyricsBusy}
                onClick={() => setNaatLibraryPage(p => Math.max(1, p - 1))}
              >Previous</button>
              <span>Page {currentLibraryPage} of {totalLibraryPages}</span>
              <button
                className="subtle-button"
                disabled={currentLibraryPage >= totalLibraryPages || lyricsBusy}
                onClick={() => setNaatLibraryPage(p => Math.min(totalLibraryPages, p + 1))}
              >Next</button>
            </div>
          </div>
        )}
      </section>
    );
  }

  function transliterationWorkspace() {
    const active = transPages[transIndex];
    return (
      <section className="panel transliteration-workspace">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">URDU → ROMAN URDU</span>
            <h2>Page transliteration</h2>
          </div>
          <span className={`status-pill ${transStatus === 'approved' ? 'approved' : ''}`}>
            <span />{transStatus}
          </span>
        </div>
        <p className="muted">Select a book and PDF page range, then extract Urdu directly from the PDF. Scanned pages use OCR; always correct OCR errors and validate Roman Urdu before approval.</p>

        <div className="transliteration-controls">
          <label>Source book
            <select value={transBookId} onChange={(e) => setTransBookId(e.target.value)}>
              <option value="">Choose a book…</option>
              {books.map((book) => <option key={book.id} value={book.id}>{book.title} — {book.original_filename}</option>)}
            </select>
          </label>
          <label>Start page
            <input type="number" min="1" max="10000" value={transStart} onChange={(e) => setTransStart(e.target.value)} />
          </label>
          <label>End page
            <input type="number" min="1" max="10000" value={transEnd} onChange={(e) => setTransEnd(e.target.value)} />
          </label>
          <button className="primary-button" onClick={loadTransPages} disabled={transBusy}>
            {transBusy ? 'Loading…' : 'Load pages'}
          </button>
          <button className="subtle-button" onClick={extractTransPages} disabled={transBusy || !transBookId}>
            {transBusy ? 'Processing…' : 'Extract Urdu from PDF'}
          </button>
        </div>

        <div className="alert success" role="status" style={{ margin: '14px 0' }}>
          Workspace debug: {transPages.length} page(s) loaded
          {active ? ` · selected page ${active.page_number} · Urdu ${transUrdu.length} chars · Roman Urdu ${transRoman.length} chars` : ' · no page selected'}
          {transBusy ? ' · processing…' : ''}
        </div>
        {transPages.length > 0 && active && <>
          <div className="trans-page-strip">
            {transPages.map((item, index) => (
              <button key={item.page_number}
                className={`trans-page-button ${index === transIndex ? 'selected' : ''}`}
                onClick={() => selectTransPage(index)}>
                <strong>{item.page_number}</strong>
                <small>{item.status}</small>
              </button>
            ))}
          </div>

          <div className="transliteration-editors">
            <label>Original Urdu
              <textarea dir="rtl" lang="ur" value={transUrdu}
                onChange={(e) => setTransUrdu(e.target.value)}
                placeholder="یہاں اردو متن درج کریں…" rows={10} maxLength={20000} />
            </label>
            <label>Roman Urdu
              <textarea dir="ltr" lang="en" value={transRoman}
                onChange={(e) => setTransRoman(e.target.value)}
                placeholder="Roman Urdu will appear here. Review and edit it…" rows={10} maxLength={40000} />
            </label>
          </div>

          <div className="transliteration-actions">
            <button className="subtle-button" onClick={generateTransliteration} disabled={transBusy || transStatus === 'approved'}>Generate Roman Urdu</button>
            <button className="subtle-button" onClick={() => saveTransliteration('draft')} disabled={transBusy}>Save draft</button>
            <button className="subtle-button" onClick={() => saveTransliteration('reviewed')} disabled={transBusy || transStatus === 'approved'}>Mark reviewed</button>
            <button className="primary-button" onClick={() => saveTransliteration('approved')} disabled={transBusy || transStatus === 'approved'}>Approve page</button>
          </div>
          <p className="muted">Page {active.page_number} of the selected range. Export includes approved pages only.</p>
        </>}

        <div className="transliteration-export">
          <div><strong>Android-ready export</strong><p className="muted">Download a UTF-8 JSON file containing approved pages only.</p></div>
          <button className="primary-button" onClick={exportTransliterations} disabled={transBusy || !transBookId}>Export approved JSON</button>
        </div>
      </section>
    );
  }

  async function logout() {
    try {
      await api('/auth/logout', { method: 'POST' });
    } finally {
      setUser(null);
      setPage('dashboard');
    }
  }

  async function upload(event: FormEvent) {
    event.preventDefault();
    setError('');
    setNotice('');

    if (!title.trim() || !author.trim()) {
      setError('Enter both the book title and author. Use Anonymous if the author is unknown.');
      return;
    }
    if (!file) {
      setError('Choose a PDF file first.');
      return;
    }
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setError('Please select a PDF file.');
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      setError('The PDF must be 50 MB or smaller.');
      return;
    }

    const form = new FormData();
    form.append('title', title);
    form.append('author', author);
    form.append('file', file);

    setBusy(true);
    try {
      await api('/books', { method: 'POST', body: form });
      setTitle('');
      setAuthor('');
      setFile(null);
      const input = document.getElementById('pdf-file') as HTMLInputElement | null;
      if (input) input.value = '';
      await loadBooks();
      setNotice('Your book has been added to the private library.');
      setPage('books');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setBusy(false);
    }
  }

  const filteredBooks = books.filter((book) =>
    `${book.title} ${book.author} ${book.original_filename}`
      .toLowerCase().includes(search.toLowerCase())
  );

  if (checking) {
    return <div className="loading-screen"><div className="brand-mark">N</div><p>Opening your library…</p></div>;
  }

  if (!user) {
    return (
      <main className="login-screen">
        <section className="login-art">
          <div className="login-brand"><span className="brand-mark">N</span><span>naatify<span className="brand-period">.</span></span></div>
          <div className="art-copy">
            <span className="eyebrow light">A HOME FOR SACRED WORDS</span>
            <h1>Preserve the words.<br />Share the devotion.</h1>
            <p>A carefully curated home for Salaams, Naats and the words that carry devotion across generations.</p>
          </div>
          <div className="art-ornament" aria-hidden="true">۞</div>
          <div className="art-footer">A library of remembrance · Made with care</div>
        </section>
        <section className="login-panel">
          <div className="login-card">
            <div className="login-symbol"><Icon name="book" size={26}/></div>
            <span className="eyebrow">PRIVATE ADMINISTRATION</span>
            <h2>Welcome back</h2>
            <p className="muted">Sign in to continue to your library.</p>
            <form onSubmit={login} className="login-form">
              <label>Username<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required /></label>
              <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></label>
              {error && <div className="alert error">{error}</div>}
              <button className="primary-button full-button" disabled={busy}>{busy ? 'Signing in…' : 'Sign in securely'} <span>→</span></button>
            </form>
            <p className="login-security">Protected admin access · Your library stays private</p>
          </div>
        </section>
      </main>
    );
  }

  async function assignNaatToCollection(naatId: string, collectionId: string) {
    setError('');
    setNotice('');

    const selectedId = collectionId || null;
    const previous = naats.find((naat) => naat.id === naatId)?.collection_id ?? null;

    setNaats((current) => current.map((naat) =>
      naat.id === naatId ? { ...naat, collection_id: selectedId } : naat
    ));

    try {
      await api(`/naats/${encodeURIComponent(naatId)}/collection`, {
        method: 'PUT',
        body: JSON.stringify({ collection_id: selectedId }),
      });
      await loadCollections();
      setNotice('Naat collection assignment updated.');
    } catch (err) {
      setNaats((current) => current.map((naat) =>
        naat.id === naatId ? { ...naat, collection_id: previous } : naat
      ));
      setError(err instanceof Error ? err.message : 'Could not update collection assignment.');
    }
  }

  function resetCollectionForm() {
    setEditingCollectionId('');
    setCollectionTitle('');
    setCollectionAuthor('');
    setCollectionDescription('');
    setCollectionCover(null);
  }

  function editCollection(collection: Collection) {
    setEditingCollectionId(collection.id);
    setCollectionTitle(collection.title);
    setCollectionAuthor(collection.author);
    setCollectionDescription(collection.description);
    setCollectionCover(null);
    setError('');
    setNotice('');
  }

  async function saveCollection(event: FormEvent) {
    event.preventDefault();

    if (!collectionTitle.trim()) {
      setError('Enter a collection title.');
      return;
    }

    setCollectionBusy(true);
    setError('');
    setNotice('');

    try {
      const payload = {
        title: collectionTitle.trim(),
        author: collectionAuthor.trim(),
        description: collectionDescription.trim(),
      };

      let collectionId = editingCollectionId;

      if (collectionId) {
        await api(`/collections/${encodeURIComponent(collectionId)}`, {
          method: 'PUT',
          body: JSON.stringify(payload),
        });
      } else {
        const created = await api('/collections', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
        collectionId = created.id;
      }

      if (collectionCover) {
        const formData = new FormData();
        formData.append('file', collectionCover);
        await api(`/collections/${encodeURIComponent(collectionId)}/cover`, {
          method: 'POST',
          body: formData,
        });
      }

      await loadCollections();
      resetCollectionForm();
      setNotice('Collection saved successfully.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save the collection.');
    } finally {
      setCollectionBusy(false);
    }
  }

  function collectionsWorkspace() {
    const sortedNaats = [...naats].sort((a, b) =>
      a.title.localeCompare(b.title)
    );

    return (
      <div className="collections-page">
        <section className="panel collection-editor">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">COLLECTION MANAGEMENT</span>
              <h2>{editingCollectionId ? 'Edit collection' : 'Create a collection'}</h2>
            </div>
          </div>

          <form className="collection-form" onSubmit={saveCollection}>
            <label>Collection title <span className="required">*</span>
              <input value={collectionTitle}
                onChange={(e) => setCollectionTitle(e.target.value)}
                placeholder="e.g. Hadaiq-e-Bakshish" maxLength={200} required />
            </label>
            <label>Author / compiler
              <input value={collectionAuthor}
                onChange={(e) => setCollectionAuthor(e.target.value)}
                placeholder="Poet or compiler" maxLength={200} />
            </label>
            <label className="collection-description">Description
              <textarea value={collectionDescription}
                onChange={(e) => setCollectionDescription(e.target.value)}
                placeholder="A short introduction to this collection" maxLength={2000} rows={3} />
            </label>
            <label className="collection-cover-input">Cover image
              <input type="file" accept="image/jpeg,image/png,image/webp"
                onChange={(e) => setCollectionCover(e.target.files?.[0] || null)} />
              <small>JPEG, PNG or WebP. Maximum 5 MB.</small>
            </label>
            <div className="collection-form-actions">
              <button className="primary-button" type="submit" disabled={collectionBusy}>
                {collectionBusy ? 'Saving…' : editingCollectionId ? 'Save changes' : 'Create collection'}
              </button>
              {editingCollectionId && (
                <button className="subtle-button" type="button"
                  onClick={resetCollectionForm} disabled={collectionBusy}>
                  Cancel editing
                </button>
              )}
            </div>
          </form>
        </section>

        <section className="collection-library">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">YOUR CATALOGUE</span>
              <h2>Collections ({collections.length})</h2>
            </div>
          </div>

          {collections.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon"><Icon name="book" size={28}/></div>
              <h3>No collections yet</h3>
              <p>Create your first collection using the form above.</p>
            </div>
          ) : (
            <div className="collection-card-grid">
              {collections.map((collection) => (
                <article className="collection-card" key={collection.id}>
                  <div className="collection-cover">
                    {collection.cover_image ? (
                      <img
                        src={`/api/v1/public/collections/${encodeURIComponent(collection.id)}/cover`}
                        alt={`${collection.title} cover`}
                      />
                    ) : (
                      <div className="collection-cover-placeholder"><Icon name="book" size={32}/></div>
                    )}
                  </div>
                  <div className="collection-card-content">
                    <h3>{collection.title}</h3>
                    <p>{collection.author || 'Author not specified'}</p>
                    {collection.description && <p className="collection-card-description">{collection.description}</p>}
                    <div className="collection-card-footer">
                      <span>{collection.naat_count} Naats</span>
                      <button className="subtle-button" type="button"
                        onClick={() => editCollection(collection)}>Edit</button>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>

        <section className="panel collection-assignments">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">ORGANISE YOUR NAATS</span>
              <h2>Assign Naats to collections</h2>
            </div>
            <button className="subtle-button" type="button"
              onClick={() => loadNaats().catch((err) => setError(err.message))}>
              <Icon name="refresh" size={16}/> Refresh
            </button>
          </div>
          <p className="muted">Choose a collection for each Naat. Select “Unassigned” to remove its collection link.</p>

          {sortedNaats.length === 0 ? (
            <div className="empty-state">
              <h3>No Naats found</h3>
              <p>Create Naats in the Naat Library before assigning them to collections.</p>
            </div>
          ) : (
            <div className="collection-assignment-list">
              {sortedNaats.map((naat) => (
                <div className="collection-assignment-row" key={naat.id}>
                  <div className="collection-assignment-info">
                    <strong>{naat.title}</strong>
                    <small>{naat.poet || 'Unknown author'}{naat.book_name ? ` · ${naat.book_name}` : ''}</small>
                  </div>
                  <select
                    aria-label={`Collection for ${naat.title}`}
                    value={naat.collection_id || ''}
                    onChange={(e) => assignNaatToCollection(naat.id, e.target.value)}
                    disabled={collectionBusy}
                  >
                    <option value="">Unassigned</option>
                    {collections.map((collection) => (
                      <option key={collection.id} value={collection.id}>{collection.title}</option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    );
  }

  const pageTitles: Record<string, { title: string; subtitle: string }> = {
    dashboard: { title: 'Your library, at a glance.', subtitle: 'Welcome back. Here is the latest from your collection.' },
    books: { title: 'Book library', subtitle: 'Manage your source books and scanned manuscripts.' },
    collections: { title: 'Naat Collections', subtitle: 'Organise Naats into curated collections, add cover images and manage assignments.' },
    poetry: { title: 'Poetry collection', subtitle: 'Individual Naats and Salaams will appear here after extraction.' },
    translations: { title: 'Translations', subtitle: 'Prepare multilingual editions for careful review.' },
    review: { title: 'Review queue', subtitle: 'Check extracted text and translations before publication.' },
    lyrics: { title: 'Naat Library', subtitle: 'Manage original Naats, language versions and publication.' },
  };

  const current = pageTitles[page] || pageTitles.dashboard;

  function navButton(item: typeof navItems[number]) {
    return (
      <button key={item.id} className={`nav-item ${page === item.id ? 'active' : ''}`}
        onClick={() => {
          setPage(item.id);
          setMobileMenu(false);
          setError('');
          setNotice('');
          if (item.id === 'collections') {
            loadNaats().catch((err) => setError(err.message));
            loadCollections().catch((err) => setError(err.message));
          }
        }}>
        <Icon name={item.icon}/><span>{item.label}</span>
        {item.id === 'books' && <span className="nav-count">{books.length}</span>}
      </button>
    );
  }

  function uploadCard() {
    return (
      <section className="panel upload-panel">
        <div className="panel-heading">
          <div><span className="eyebrow">ADD TO YOUR ARCHIVE</span><h2>Upload a book</h2></div>
          <span className="heading-icon"><Icon name="upload" size={21}/></span>
        </div>
        <p className="muted">Add a scanned Urdu PDF to your private library. We’ll prepare it for poetry extraction.</p>
        <form className="upload-form" onSubmit={upload}>
          <label>Book title<input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Kulliyat-e-Naat" maxLength={200} required /></label>
          <label>Author <span className="required">*</span><input value={author} onChange={(e) => setAuthor(e.target.value)} placeholder="Poet or compiler (or Anonymous)" maxLength={200} required /></label>
          <label className="file-label">PDF manuscript
            <span className="dropzone">
              <Icon name="upload" size={25}/>
              <strong>{file ? file.name : 'Choose a PDF to upload'}</strong>
              <small>{file ? `${(file.size / (1024 * 1024)).toFixed(2)} MB` : 'PDF format · Maximum 50 MB'}</small>
              <input id="pdf-file" type="file" accept=".pdf,application/pdf" onChange={(e) => setFile(e.target.files?.[0] || null)} required/>
            </span>
          </label>
          {error && <div className="alert error">{error}</div>}
          {notice && <div className="alert success">{notice}</div>}
          <button className="primary-button full-button" disabled={busy}><Icon name="upload" size={17}/>{busy ? 'Uploading book…' : 'Upload to library'}<span>→</span></button>
        </form>
        <div className="privacy-note"><span>✓</span> Files are stored privately and linked to your admin library.</div>
      </section>
    );
  }

  function bookList(compact = false) {
    return (
      <section className="panel library-panel">
        <div className="panel-heading">
          <div><span className="eyebrow">YOUR SOURCE MATERIAL</span><h2>Recent books</h2></div>
          <button className="subtle-button" onClick={() => loadBooks().catch((err) => setError(err.message))}><Icon name="refresh" size={16}/> Refresh</button>
        </div>
        <div className="search-box"><Icon name="search" size={18}/><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search your books…" /></div>
        {filteredBooks.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon"><Icon name="book" size={28}/></div>
            <h3>{books.length ? 'No matching books' : 'Your library starts here'}</h3>
            <p>{books.length ? 'Try another title or author.' : 'Upload your first scanned book to begin building your collection.'}</p>
            {!books.length && compact && <button className="text-button" onClick={() => setPage('books')}>Add your first book <span>→</span></button>}
          </div>
        ) : (
          <div className="book-list">
            {filteredBooks.map((book) => (
              <article className="book-row" key={book.id}>
                <div className="book-cover"><Icon name="book" size={25}/></div>
                <div className="book-details"><h3>{book.title}</h3><p>{book.author || 'Author not specified'}</p><small>{book.original_filename} · {(book.file_size / (1024 * 1024)).toFixed(2)} MB</small></div>
                <span className={`status-pill ${book.status === 'approved' ? 'approved' : ''}`}><span/> {book.status}</span>
                <button className="subtle-button details-button" onClick={() => inspectBook(book)} disabled={!!inspectingId}>
                  {inspectingId === book.id ? 'Inspecting…' : 'Details'}
                </button>
              </article>
            ))}
          </div>
        )}
        {compact && books.length > 0 && <button className="text-button view-all" onClick={() => setPage('books')}>View all books <span>→</span></button>}
      </section>
    );
  }

  function comingSoon(title: string, description: string, icon: string) {
    return (
      <section className="feature-page">
        <div className="feature-hero">
          <div className="feature-icon"><Icon name={icon} size={29}/></div>
          <span className="eyebrow">COMING NEXT</span>
          <h2>{title}</h2>
          <p>{description}</p>
          <div className="feature-steps">
            <div><span>01</span><strong>Extract</strong><small>Identify poems and verses from scanned pages.</small></div>
            <div><span>02</span><strong>Refine</strong><small>Correct text and preserve original verse order.</small></div>
            <div><span>03</span><strong>Approve</strong><small>Review the content before it is published.</small></div>
          </div>
          <button className="primary-button" onClick={() => setPage('books')}>Go to book library <span>→</span></button>
        </div>
      </section>
    );
  }

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileMenu ? 'sidebar-open' : ''}`}>
        <div className="sidebar-brand"><span className="brand-mark">N</span><span>naatify<span className="brand-period">.</span><small>THE POETRY ARCHIVE</small></span></div>
        <div className="sidebar-label">WORKSPACE</div>
        <nav>{navItems.map(navButton)}</nav>
        <div className="sidebar-bottom">
          <div className="sidebar-note"><span className="note-star">✳</span><strong>Preserve every verse.</strong><p>A home for words that matter.</p></div>
          <div className="profile-row"><div className="avatar">{user.username.slice(0, 1).toUpperCase()}</div><div className="profile-text"><strong>{user.username}</strong><small>Library administrator</small></div><button className="logout-button" title="Sign out" onClick={logout}><Icon name="logout" size={18}/></button></div>
        </div>
      </aside>

      {mobileMenu && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setMobileMenu(false)}/>}

      <main className="main-area">
        <header className="topbar">
          <button className="mobile-menu-button" onClick={() => setMobileMenu(!mobileMenu)} aria-label="Toggle navigation"><Icon name="menu"/></button>
          <div className="breadcrumb">Naatify <span>/</span> <strong>{navItems.find((item) => item.id === page)?.label || 'Dashboard'}</strong></div>
          <div className="topbar-right"><span className="private-indicator"><span/> Private workspace</span><div className="avatar small-avatar">{user.username.slice(0, 1).toUpperCase()}</div></div>
        </header>

        <div className="page-content">
          <div className="page-heading"><div><span className="eyebrow">NAATIFY ADMINISTRATION</span><h1>{current.title}</h1><p>{current.subtitle}</p></div>
            {page === 'dashboard' && <button className="primary-button heading-action" onClick={() => setPage('books')}><Icon name="upload" size={17}/> Add a book</button>}
          </div>

          {error && <div className="alert error global-alert">{error}<button onClick={() => setError('')} aria-label="Dismiss">×</button></div>}
          {notice && page !== 'books' && <div className="alert success global-alert">{notice}<button onClick={() => setNotice('')} aria-label="Dismiss">×</button></div>}

          {page === 'dashboard' && <>
            <div className="welcome-banner"><div className="banner-copy"><span className="eyebrow light">YOUR DIGITAL HERITAGE</span><h2>Every verse deserves<br/>to be remembered.</h2><p>Build a lasting, searchable home for sacred poetry.</p><button className="banner-button" onClick={() => setPage('books')}>Explore your library <span>→</span></button></div><div className="banner-art" aria-hidden="true"><div className="art-ring ring-one"/><div className="art-ring ring-two"/><span>۞</span></div></div>
            <div className="stats-grid">
              <article className="stat-card"><div className="stat-top"><span>Total books</span><span className="stat-icon"><Icon name="book"/></span></div><strong>{books.length}</strong><small>Source manuscripts</small></article>
              <article className="stat-card"><div className="stat-top"><span>Poems extracted</span><span className="stat-icon"><Icon name="poetry"/></span></div><strong>—</strong><small>Extraction not configured</small></article>
              <article className="stat-card"><div className="stat-top"><span>Translations</span><span className="stat-icon"><Icon name="language"/></span></div><strong>—</strong><small>Translation workflow pending</small></article>
              <article className="stat-card"><div className="stat-top"><span>Awaiting review</span><span className="stat-icon"><Icon name="check"/></span></div><strong>—</strong><small>Review workflow pending</small></article>
            </div>
            <div className="dashboard-grid">{bookList(true)}{uploadCard()}</div>
            <div className="next-step"><div className="next-step-icon"><Icon name="spark" size={22}/></div><div><strong>The next chapter: poetry extraction</strong><p>Once your books are uploaded, the next step is extracting Urdu poetry while preserving the original page and verse order.</p></div><button className="text-button" onClick={() => setPage('poetry')}>Explore workflow <span>→</span></button></div>
          </>}

          {page === 'book-details' && (
            <section className="panel inspection-page">
              <button className="subtle-button" onClick={() => setPage('books')}>← Back to book library</button>
              {!inspection ? (
                <div className="empty-state">
                  <div className="empty-icon"><Icon name="file" size={28}/></div>
                  <h3>{inspectingId ? 'Inspecting PDF…' : 'Inspection unavailable'}</h3>
                  <p>{inspectingId ? 'Reading page metadata and checking for selectable text. No OCR is running.' : 'The PDF could not be inspected. Check the error message above and backend logs.'}</p>
                </div>
              ) : (
                <>
                  <div className="inspection-title">
                    <span className="eyebrow">BOOK DETAILS</span>
                    <h2>{inspection.book.title}</h2>
                    <p>{inspection.book.original_filename}</p>
                  </div>
                  <div className="inspection-stats">
                    <div><small>Total pages</small><strong>{inspection.inspection.page_count}</strong></div>
                    <div><small>Pages with text</small><strong>{inspection.inspection.pages_with_selectable_text}</strong></div>
                    <div><small>Likely scanned</small><strong>{inspection.inspection.pages_likely_scanned}</strong></div>
                  </div>
                  <div className="inspection-note">
                    <strong>{inspection.inspection.text_extraction_available ? 'Selectable text detected' : 'Scanned pages likely'}</strong>
                    <p>{inspection.inspection.text_extraction_available ? 'Some pages contain extractable text. Image-based pages may still require OCR.' : 'No selectable text was found. Urdu OCR will likely be required to read the page images.'}</p>
                  </div>
                  <h3 className="page-table-title">Page inspection</h3>
                  <div className="page-table-wrap">
                    <table className="page-table">
                      <thead><tr><th>Page</th><th>Dimensions (pt)</th><th>Text characters</th><th>Classification</th><th>Extracted sample</th><th>Action</th></tr></thead>
                      <tbody>
                        {inspection.inspection.pages.map((item) => (
                          <tr key={item.page_number}>
                            <td>{item.page_number}</td>
                            <td>{item.width_pt} × {item.height_pt}</td>
                            <td>{item.text_characters}</td>
                            <td><span className={`status-pill ${item.has_selectable_text ? 'approved' : ''}`}><span/>{item.has_selectable_text ? 'Text found' : 'Likely scan'}</span></td>
                            <td className="sample-cell">{item.text_sample || '—'}</td>
                            <td><button className="subtle-button" onClick={() => createNaatFromBookPage(inspection.book, item.page_number)}>Create Naat</button></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </section>
          )}

          {page === 'books' && <div className="books-page-grid">{uploadCard()}{bookList(false)}</div>}
          {page === 'collections' && collectionsWorkspace()}
          {page === 'poetry' && comingSoon('Poetry collection', 'A structured collection of individual Naats and Salaams, extracted from your source books and ready for editing.', 'poetry')}
          {page === 'translations' && transliterationWorkspace()}
          {page === 'lyrics' && lyricsStudio()}
          {page === 'review' && comingSoon('Editorial review', 'Review OCR output, compare it with the source pages and approve content before it reaches readers.', 'check')}
          <footer className="page-footer"><div className="footer-brand"><span className="brand-mark mini-mark">N</span> Naatify</div><span>Preserving words. Sharing devotion.</span><span>Private library workspace</span></footer>
        </div>
      </main>
    </div>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
