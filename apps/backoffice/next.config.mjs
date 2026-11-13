/** API calls go to /v1 on the same origin, so the session cookie and CSRF
 * work without cross-site rules. In development they are proxied to Django. */
const API = process.env.TENMINA_API_URL || 'http://localhost:8000';

export default {
  reactStrictMode: true,
  transpilePackages: ['@tenmina/web-ui', '@tenmina/api-client'],
  async rewrites() {
    return [{ source: '/v1/:path*', destination: `${API}/v1/:path*` }];
  },
};
