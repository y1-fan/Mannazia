import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { BookshelfPage } from '../pages/BookshelfPage';
import { LanguageSwitch } from '../components/LanguageSwitch';
import { I18nProvider } from '../i18n';
import { bookSummary, installFetch, jsonResponse } from './fixtures';

describe('language switching', () => {
  it('renders Chinese and switches back to English', async () => {
    const user = userEvent.setup();
    installFetch({
      'GET /api/books?limit=200': () =>
        jsonResponse({ items: [bookSummary], total: 1, limit: 200, offset: 0 }),
    });
    render(
      <I18nProvider initialLanguage="zh">
        <MemoryRouter>
          <BookshelfPage />
          <LanguageSwitch />
        </MemoryRouter>
      </I18nProvider>,
    );

    expect(await screen.findByRole('heading', { name: '你的书架' })).toBeInTheDocument();
    expect(screen.getByPlaceholderText('搜索标题、作者、标签和元数据……')).toBeInTheDocument();
    expect(screen.getByTitle(/Every page has been verified|所有页面均已验证/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Switch to English/ }));

    expect(await screen.findByRole('heading', { name: 'Your library' })).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText('Search titles, creators, tags and metadata…'),
    ).toBeInTheDocument();
    expect(window.localStorage.getItem('mannazia.language')).toBe('en');
  });
});
