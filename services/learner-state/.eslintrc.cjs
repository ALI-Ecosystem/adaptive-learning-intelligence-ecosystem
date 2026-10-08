/**
 * Architectural guard rails, not style:
 *  - src/core/ is the pure functional core (no I/O) and must not import
 *    from src/infra/ (SCRUM-31).
 *  - Prisma rules 1, 2 and 4 of architecture App. C.2, plus #23: no
 *    generated query API outside src/infra/admin/ (SCRUM-34).
 *
 * The Prisma checks are syntactic: they recognise a client by its name
 * (`tx`, `prisma`, `db`, `*Client`, `*Prisma`). Keep to those names.
 * test/lint/guard-rails.spec.ts proves each rule fires.
 */

const PRISMA_CLIENT_NAME = '/^(tx|db|prisma\\w*|\\w*Client|\\w*Prisma)$/';
const GENERATED_API =
  '/^(findUnique|findUniqueOrThrow|findFirst|findFirstOrThrow|findMany|create|createMany|createManyAndReturn|update|updateMany|updateManyAndReturn|upsert|delete|deleteMany|count|aggregate|groupBy)$/';

const RAW_SQL_RULES = [
  {
    selector: 'MemberExpression[property.name=/^\\$(executeRawUnsafe|queryRawUnsafe)$/]',
    message:
      'App. C.2 rule 2: use the tagged templates tx.$queryRaw`...` / tx.$executeRaw`...`; never the *Unsafe variants (SQL injection, T3).',
  },
  {
    selector: "CallExpression[callee.property.name='$transaction'][arguments.0.type='ArrayExpression']",
    message:
      'App. C.2 rule 1: use the interactive form $transaction(async (tx) => ...), never the array form.',
  },
  {
    selector: "CallExpression[callee.property.name='$transaction'][arguments.length<2]",
    message:
      'App. C.2 rule 4: pass options with an explicit timeout, or use withLearnerRead / withEventWrite.',
  },
  {
    selector: "MemberExpression[property.name=/^\\$(queryRaw|executeRaw)$/][object.name!='tx']",
    message:
      'App. C.2 rule 1: raw SQL runs on the `tx` handle inside one interactive transaction (withLearnerRead / withEventWrite), never on the client directly.',
  },
];

const GENERATED_API_MESSAGE =
  "Architecture #23: Prisma's generated query API is not used on the write path or for RLS-scoped reads; write raw SQL on `tx`. Config/admin reads belong in src/infra/admin/.";

const GENERATED_API_RULES = [
  {
    // tx.model.findMany(...), prisma.model.create(...)
    selector: `CallExpression[callee.property.name=${GENERATED_API}][callee.object.object.name=${PRISMA_CLIENT_NAME}]`,
    message: GENERATED_API_MESSAGE,
  },
  {
    // this.prisma.model.findMany(...)
    selector: `CallExpression[callee.property.name=${GENERATED_API}][callee.object.object.property.name=${PRISMA_CLIENT_NAME}]`,
    message: GENERATED_API_MESSAGE,
  },
];

module.exports = {
  root: true,
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 2022,
    sourceType: 'module',
  },
  env: {
    node: true,
    es2022: true,
  },
  ignorePatterns: ['dist/', 'node_modules/', 'coverage/'],
  rules: {
    'no-restricted-syntax': ['error', ...RAW_SQL_RULES, ...GENERATED_API_RULES],
  },
  overrides: [
    {
      files: ['src/core/**/*.ts'],
      rules: {
        'no-restricted-imports': [
          'error',
          {
            patterns: [
              {
                group: ['**/infra', '**/infra/**'],
                message:
                  'src/core/ must stay I/O-free. Pass values and callbacks in; do not import from src/infra/.',
              },
            ],
          },
        ],
      },
    },
    {
      // Config and admin reads may use the generated API (App. C.2).
      files: ['src/infra/admin/**/*.ts'],
      rules: {
        'no-restricted-syntax': ['error', ...RAW_SQL_RULES],
      },
    },
  ],
};
