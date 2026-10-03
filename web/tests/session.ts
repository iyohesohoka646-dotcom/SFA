export const session = process.env.CDAF_BROWSER_TEST_SESSION;
if (!session) throw new Error('Playwright must supply its private fixture session');
