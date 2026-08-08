const { createProxyMiddleware } = require('http-proxy-middleware');

module.exports = function(app) {
  // Proxy specific API endpoints to backend without stripping path prefixes
  const apiPaths = [
    '/upload-excel',
    '/generate-timetable', 
    '/get-timetable-status',
    '/export-timetable',
    '/api',
    '/interactive',
    '/_dash-component-suites',
    '/_dash-layout',
    '/_dash-dependencies',
    '/_dash-update-component',
    '/_favicon.ico',
    '/assets'
  ];

  app.use(
    createProxyMiddleware(apiPaths, {
      target: 'http://localhost:7860',
      changeOrigin: true,
      ws: false,
    })
  );
};
