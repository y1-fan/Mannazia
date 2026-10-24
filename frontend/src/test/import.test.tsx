import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ImportPage } from '../pages/ImportPage';
import { bookDetail, installFetch, jsonResponse } from './fixtures';
import type { ImportPreview } from '../types';

const preview: ImportPreview = {
  manifest_url: 'https://example.org/iiif/book2/manifest',
  api_version: '3',
  title: 'The Book of Hours',
  creator: 'Example Atelier',
  description: 'A luminous book of hours.',
  language: 'Latin',
  date: '1450',
  rights: 'Permission required.',
  rights_uri: 'https://example.org/rights/inc',
  required_statement: { label: 'Attribution', value: 'Image courtesy of the Example Library.' },
  thumbnail_url: 'https://example.org/thumb.jpg',
  canvas_count: 3,
  image_canvas_count: 3,
  metadata: [{ label: 'Shelfmark', value: 'MS 7' }],
  summary: 'A luminous book of hours.',
  provider: 'Example Library',
  homepage: [],
  rendering: [],
  warnings: ['This is a test warning.'],
  preview_token: 'token-1',
  duplicate_of: null,
  duplicate_title: null,
};

function renderImport() {
  return render(
    <MemoryRouter initialEntries={['/import']}>
      <Routes>
        <Route path="/import" element={<ImportPage />} />
        <Route path="/books/:bookId" element={<div>Imported book page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ImportPage', () => {
  it('previews a Manifest and imports it with metadata overrides', async () => {
    const user = userEvent.setup();
    let posted: Record<string, unknown> | null = null;
    installFetch({
      'POST /api/import/preview': () => jsonResponse(preview),
      'POST /api/books': (init) => {
        posted = JSON.parse(String(init?.body));
        return jsonResponse(bookDetail, 201);
      },
    });
    renderImport();

    await user.type(
      screen.getByLabelText('IIIF Manifest URL'),
      'https://example.org/iiif/book2/manifest',
    );
    await user.click(screen.getByRole('button', { name: 'Preview' }));

    expect(await screen.findByRole('heading', { name: 'The Book of Hours' })).toBeInTheDocument();
    expect(screen.getByText('Presentation API 3')).toBeInTheDocument();
    expect(screen.getByText(/test warning/i)).toBeInTheDocument();
    expect(screen.getByText(/Rights and attribution|Image courtesy/i)).toBeInTheDocument();

    const titleInput = screen.getByLabelText('Title');
    await user.clear(titleInput);
    await user.type(titleInput, 'My Book of Hours');
    await user.click(screen.getByRole('button', { name: /Add to library/i }));

    expect(await screen.findByText('Imported book page')).toBeInTheDocument();
    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted).toMatchObject({
      manifest_url: 'https://example.org/iiif/book2/manifest',
      preview_token: 'token-1',
      title: 'My Book of Hours',
    });
  });

  it('shows duplicate books instead of offering an import', async () => {
    const user = userEvent.setup();
    installFetch({
      'POST /api/import/preview': () =>
        jsonResponse({ ...preview, duplicate_of: 'b1', duplicate_title: 'Existing book' }),
    });
    renderImport();
    await user.type(
      screen.getByLabelText('IIIF Manifest URL'),
      'https://example.org/iiif/book2/manifest',
    );
    await user.click(screen.getByRole('button', { name: 'Preview' }));
    expect(await screen.findByText('Already in the library')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Add to library/i })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open the existing book' })).toHaveAttribute(
      'href',
      '/books/b1',
    );
  });

  it('rejects non-HTTP URLs before calling the API', async () => {
    const user = userEvent.setup();
    const mock = installFetch({});
    renderImport();
    await user.type(screen.getByLabelText('IIIF Manifest URL'), 'ftp://example.org/m.json');
    await user.click(screen.getByRole('button', { name: 'Preview' }));
    expect(await screen.findByText(/Only HTTP and HTTPS/i)).toBeInTheDocument();
    expect(mock).not.toHaveBeenCalled();
  });
});
