export default async function globalTeardown(): Promise<void> {
  await globalThis.__LS_POSTGRES__?.stop();
}
