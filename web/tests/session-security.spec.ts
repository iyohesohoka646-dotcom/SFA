import {expect, test} from '@playwright/test';

for (const [port, route, prior] of [
  [8877, '/api/v1/project', 'browser-test-session'],
  [8878, '/api/v1/workspace', 'workspace-test-session'],
  [8879, '/api/v1/research/runs', 'research-test-session'],
] as const) {
  test(`security: public prior fixture bearer cannot authorize port ${port}`, async ({request}) => {
    const response = await request.get(`http://127.0.0.1:${port}${route}`, {headers: {Authorization: `Bearer ${prior}`}});
    expect(response.status()).toBe(401);
  });
}
