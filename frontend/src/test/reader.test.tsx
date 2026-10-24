import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ReaderPage } from '../pages/ReaderPage';
import { bookDetail, canvas, installFetch, jsonResponse } from './fixtures';

const { osdMock } = vi.hoisted(() => {
  const viewer = {
    addHandler: vi.fn(),
    open: vi.fn(),
    destroy: vi.fn(),
    viewport: {
      zoomBy: vi.fn(),
      goHome: vi.fn(),
    },
  };
  return {
    osdMock: vi.fn(() => viewer),
  };
});

vi.mock('openseadragon', () => ({ default: osdMock }));

function renderReader() {
  return render(
    <MemoryRouter initialEntries={['/books/b1/read?page=1']}>
      <Routes>
        <Route path="/books/:bookId/read" element={<ReaderPage />} />
        <Route path="/books/:bookId" element={<div>Book detail</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ReaderPage', () => {
  it('turns pages and persists the reading position', async () => {
    const user = userEvent.setup();
    const items = [canvas(1), canvas(2), canvas(3)];
    const saved: Array<Record<string, unknown>> = [];
    installFetch({
      'GET /api/books/b1': () => jsonResponse(bookDetail),
      'GET /api/books/b1/canvases': () =>
        jsonResponse({ book_id: 'b1', download_state: 'offline', total: 3, items }),
      'GET /api/books/b1/progress': () =>
        jsonResponse({
          book_id: 'b1',
          canvas_id: 'c2',
          source_canvas_id: 'https://example.org/iiif/canvas/2',
          sequence_index: 1,
          updated_at: '2026-10-01T10:00:00Z',
        }),
      'PUT /api/books/b1/progress': (init) => {
        saved.push(JSON.parse(String(init?.body)));
        return jsonResponse({
          book_id: 'b1',
          canvas_id: 'c2',
          source_canvas_id: 'https://example.org/iiif/canvas/2',
          sequence_index: 1,
          updated_at: '2026-10-01T10:00:00Z',
        });
      },
    });
    renderReader();

    expect(await screen.findByText('The Book of Hours')).toBeInTheDocument();
    // The ?page=1 query takes precedence over the stored page 2.
    expect(screen.getByText('Page 1 of 3')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(await screen.findByText('Page 2 of 3')).toBeInTheDocument();

    await waitFor(() => expect(saved.length).toBeGreaterThan(0), { timeout: 2500 });
    expect(saved.at(-1)).toMatchObject({
      canvas_id: 'c2',
      source_canvas_id: 'https://example.org/iiif/canvas/2',
      sequence_index: 1,
    });
  });

  it('shows a useful message for a canvas without a supported image', async () => {
    const items = [canvas(1, { image_service_id: null, image_url: null, unsupported: true })];
    installFetch({
      'GET /api/books/b1': () => jsonResponse(bookDetail),
      'GET /api/books/b1/canvases': () =>
        jsonResponse({ book_id: 'b1', download_state: 'online', total: 1, items }),
      'GET /api/books/b1/progress': () =>
        jsonResponse({
          book_id: 'b1',
          canvas_id: null,
          source_canvas_id: null,
          sequence_index: 0,
          updated_at: null,
        }),
      'PUT /api/books/b1/progress': () =>
        jsonResponse({
          book_id: 'b1',
          canvas_id: null,
          source_canvas_id: null,
          sequence_index: 0,
          updated_at: null,
        }),
    });
    renderReader();
    expect(await screen.findByText('This page cannot be displayed')).toBeInTheDocument();
    expect(screen.getByText(/audio, video/i)).toBeInTheDocument();
  });
});
