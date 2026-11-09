// Run in the authorized browser runtime; never execute these via shell browser control.
// Pass the current tab binding. Credentials are transient arguments, never logged.
export async function inspectLogin(tab) {
  return { url: await tab.url(), snapshot: await tab.playwright.domSnapshot() };
}
export async function openLogin(tab) {
  await tab.playwright.getByRole('link', { name: /^登录\/注册/ }).click();
  await tab.playwright.getByPlaceholder('手机号', { exact: true }).filter({ visible: true }).waitFor({ state: 'visible', timeoutMs: 15000 });
}
export async function fillPhone(tab, phone) {
  if (typeof phone !== 'string' || !/^1[0-9]{10}$/.test(phone)) throw new Error('请提供有效的中国大陆手机号');
  await tab.playwright.getByPlaceholder('手机号', { exact: true }).filter({ visible: true }).fill(phone);
}
export async function requestSms(tab) {
  await tab.playwright.getByText('发送验证码', { exact: true }).filter({ visible: true }).click();
  // Inspect fresh UI: CAPTCHA may appear. Click completion does not prove SMS delivery.
}
export async function fillSmsCode(tab, code) {
  if (typeof code !== 'string' || !/^[0-9]{6}$/.test(code)) throw new Error('验证码须为6位字符串，保留前导零');
  await tab.playwright.getByPlaceholder('短信验证码', { exact: true }).filter({ visible: true }).fill(code);
}
export async function keepLoginForUser(tab) { await tab.markHandoff(); }
// Agreement acceptance and CAPTCHA actions require current UI and action-time approval.
// Do not hardcode coordinates or slider distances. Verify account UI after submission.
