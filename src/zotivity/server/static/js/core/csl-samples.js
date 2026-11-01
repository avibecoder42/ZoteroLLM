// Beispiele für die Vorschau im CSL-Editor: je ein typischer Dokumenttyp, erfundene englische Angaben (CSL-JSON).
// __locator: Seitenangabe im Beleg, damit auch „S. 12“ sichtbar wird.
import { t } from './i18n.js';

const person = (family, given) => ({ family, given });

export const SAMPLES = () => [
  { label: t('Buch'), item: {
    id: 'book', type: 'book', title: 'Social Work in the Digital Age', author: [person('Miller', 'Anna'), person('Okoye', 'Ben')],
    edition: '2', publisher: 'Example Press', 'publisher-place': 'London', issued: { 'date-parts': [[2019]] }, __locator: '45',
  } },
  { label: t('Sammelbandbeitrag'), item: {
    id: 'chapter', type: 'chapter', title: 'Online counselling: Opportunities and limits', author: [person('Nakamura', 'Lea')],
    editor: [person('Brooks', 'Tom')], 'container-title': 'Handbook of Counselling', publisher: 'Example Press', 'publisher-place': 'New York',
    page: '115-132', issued: { 'date-parts': [[2021]] }, __locator: '120',
  } },
  { label: t('Zeitschriftenartikel'), item: {
    id: 'article', type: 'article-journal', title: 'Writing with machines: How students use generative AI in academic essays',
    author: [person('Lindqvist', 'Maja'), person('Okafor', 'Chinedu')], 'container-title': 'Teaching & Technology Review',
    volume: '12', issue: '3', page: '41-58', DOI: '10.5555/ttr.2025.041', issued: { 'date-parts': [[2025, 3]] }, __locator: '43',
  } },
  { label: t('Artikel, vier Autor:innen'), item: {
    id: 'article4', type: 'article-journal', title: 'Generative AI as a writing tutor: A randomised field experiment',
    author: [person('Tanaka', 'Hiro'), person('Novak', 'Petra'), person('Castillo', 'Rafael'), person('Weber', 'Jonas')],
    'container-title': 'Higher Education Futures', volume: '8', page: '7-29', issued: { 'date-parts': [[2024]] }, __locator: '9',
  } },
  { label: t('Zeitungsartikel'), item: {
    id: 'newspaper', type: 'article-newspaper', title: 'AI in the classroom', author: [person('Harper', 'Lea')],
    'container-title': 'The Daily Example', page: 'A20', issued: { 'date-parts': [[2024, 3, 12]] }, __locator: 'A20',
  } },
  { label: t('Webseite'), item: {
    id: 'webpage', type: 'webpage', title: 'Guidelines: Generative AI in teaching', author: [{ literal: 'Example University' }],
    URL: 'https://www.example.org/ai-guidelines', issued: { 'date-parts': [[2025, 2, 1]] }, accessed: { 'date-parts': [[2026, 10, 1]] },
  } },
  { label: t('Hochschulschrift'), item: {
    id: 'thesis', type: 'thesis', genre: 'Master’s thesis', title: 'Feedback from language models in writing centres',
    author: [person('Weber', 'Jonas')], publisher: 'University of Example', 'publisher-place': 'Toronto',
    issued: { 'date-parts': [[2023]] },
  } },
  { label: t('Bericht'), item: {
    id: 'report', type: 'report', title: 'Digital skills in higher education: Report 2022', author: [{ literal: 'Example Agency for Education' }],
    publisher: 'Example Agency for Education', 'publisher-place': 'Ottawa', number: '7', issued: { 'date-parts': [[2022]] },
  } },
  { label: t('Herausgegebenes Buch'), item: {
    id: 'edited', type: 'book', title: 'Handbook of Counselling', editor: [person('Brooks', 'Tom'), person('Garcia', 'Sara')],
    publisher: 'Example Press', 'publisher-place': 'New York', issued: { 'date-parts': [[2020]] },
  } },
];
