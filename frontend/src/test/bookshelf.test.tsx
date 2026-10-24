import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { BookshelfPage } from '../pages/BookshelfPage';
import { bookSummary, installFetch, jsonResponse } from './fixtures';

function renderShelf() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route index element={<BookshelfPage />} />
        <Route path="/import" element={<div>Import screen</div>} />
        <Route path="/books/:bookId" element={<div>Book screen</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('BookshelfPage', () => {
  it('shows a useful empty state for a new library', async () => {
    installFetch({
      'GET /api/books?limit=200': () =>
        jsonResponse({ items: [], total: 0, limit: 200, offset: 0 }),
    });
    renderShelf();
    expect(await screen.findByText('The first shelf is waiting')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Import your first book/i })).toHaveAttribute(
      'href',
      '/import',
    );
  });

  it('renders books and links to details', async () => {
    installFetch({
      'GET /api/books?limit=200': () =>
        jsonResponse({ items: [bookSummary], total: 1, limit: 200, offset: 0 }),
    });
    renderShelf();
    expect(await screen.findByText('The Book of Hours')).toBeInTheDocument();
    expect(screen.getByText('Example Atelier')).toBeInTheDocument();
    expect(screen.getByTitle(/Every page has been verified/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /The Book of Hours/ })).toHaveAttribute(
      'href',
      '/books/b1',
    );
  });

  it('requests a filtered state when a chip is chosen', async () => {
    const user = userEvent.setup();
    const mock = installFetch({
      'GET /api/books?limit=200': () =>
        jsonResponse({ items: [bookSummary], total: 1, limit: 200, offset: 0 }),
      'GET /api/books?state=offline&limit=200': () =>
        jsonResponse({ items: [bookSummary], total: 1, limit: 200, offset: 0 }),
    });
    renderShelf();
    await screen.findByText('The Book of Hours');
    await user.click(screen.getByRole('button', { name: 'Offline' }));
    await waitFor(() =>
      expect(mock).toHaveBeenCalledWith(
        '/api/books?state=offline&limit=200',
        expect.anything(),
      ),
    );
    expect(await screen.findByText('The Book of Hours')).toBeInTheDocument();
  });
});
