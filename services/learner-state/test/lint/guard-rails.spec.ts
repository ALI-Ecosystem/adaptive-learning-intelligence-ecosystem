/**
 * SCRUM-34: proves each guard-rail lint rule in .eslintrc.cjs fires (and
 * does not fire on the allowed form). `npm run lint` runs in CI, so a
 * violation in src/ fails the build.
 */
import * as path from 'node:path';
import { ESLint } from 'eslint';

const SERVICE_ROOT = path.resolve(__dirname, '../..');
const eslint = new ESLint({ cwd: SERVICE_ROOT });

async function violations(code: string, file = 'src/infra/write-path/example.ts'): Promise<string[]> {
  const [result] = await eslint.lintText(code, { filePath: path.join(SERVICE_ROOT, file) });
  return (result?.messages ?? []).map((m) => `${m.ruleId}: ${m.message}`);
}

describe('guard-rail lint', () => {
  describe('rejects', () => {
    it.each([
      ['$executeRawUnsafe', 'await tx.$executeRawUnsafe(`DELETE FROM t WHERE id = ${id}`);', /rule 2/],
      ['$queryRawUnsafe', "await tx.$queryRawUnsafe('SELECT 1');", /rule 2/],
      ['array-form $transaction', 'await prisma.$transaction([a, b], { timeout: 1 });', /rule 1: use the interactive form/],
      ['$transaction without a timeout', 'await prisma.$transaction(async (tx) => 1);', /rule 4/],
      ['raw SQL on the client, outside a transaction', 'await prisma.$executeRaw`SELECT 1`;', /rule 1: raw SQL runs on the `tx` handle/],
      ['raw SQL on this.prisma', 'await this.prisma.$queryRaw`SELECT 1`;', /rule 1: raw SQL runs on the `tx` handle/],
      ['generated API on tx', 'await tx.learnerConceptState.findMany();', /#23/],
      ['generated API on a client', 'await ingestClient.processedEvent.create({ data });', /#23/],
      ['generated API on this.prisma', 'await this.prisma.modelConfig.update({ where, data });', /#23/],
    ])('%s', async (_name, code, expected) => {
      const found = await violations(code);
      expect(found.some((m) => expected.test(m))).toBe(true);
    });

    it('generated API in src/core/ too, not only write-path folders', async () => {
      expect(await violations('await tx.state.findMany();', 'src/core/x.ts')).not.toEqual([]);
    });

    it('*Unsafe even in src/infra/admin/', async () => {
      expect(await violations("await prisma.$queryRawUnsafe('SELECT 1');", 'src/infra/admin/x.ts')).not.toEqual([]);
    });
  });

  describe('allows', () => {
    it.each([
      ['tagged raw SQL on tx', 'await tx.$queryRaw`SELECT ${id}`;'],
      ['interactive $transaction with a timeout', 'await prisma.$transaction(async (tx) => 1, { timeout: 5000 });'],
      ['Map/Set methods with generated-API names', 'this.cache.delete(key); counts.update(x); seen.count();'],
    ])('%s', async (_name, code) => {
      expect(await violations(code)).toEqual([]);
    });

    it('generated API in src/infra/admin/', async () => {
      expect(await violations('await prisma.modelConfig.findMany();', 'src/infra/admin/model-config.ts')).toEqual([]);
    });
  });

  it('the current src/ tree is clean', async () => {
    const results = await eslint.lintFiles(['src/**/*.ts']);
    expect(results.flatMap((r) => r.messages.map((m) => `${r.filePath}: ${m.message}`))).toEqual([]);
  });
});
