// Run in the pinned Medusa runtime; argument is the compiled patched middleware.
const assert = require('node:assert/strict');
const { errorHandler } = require('@medusajs/framework/http');
const { PostgreSqlExceptionConverter } = require('@mikro-orm/postgresql');
const handler = process.argv[2] ? require(process.argv[2]).default.errorHandler : errorHandler();
const converter = new PostgreSqlExceptionConverter();
const logger = { error() {}, info() {} };
function response(error) {
  let status, body;
  const res = { status(value) { status = value; return this; }, json(value) { body = value; } };
  handler(error, { scope: { resolve() { return logger; } } }, res, () => {});
  return { status, body };
}
function databaseError(code, constraint) {
  return converter.convertException(Object.assign(new Error('private SQL must not reach client'), { code, constraint }));
}
const rejection = response(databaseError('23514', 'bench_reference_stock'));
assert.equal(rejection.status, 400);
assert.equal(rejection.body.type, 'not_allowed');
assert.equal(rejection.body.message, 'Insufficient stock for reservation');
for (const error of [databaseError('23514', 'unrelated_check'), databaseError('23514'),
                     databaseError('XX000', 'bench_reference_stock'), new Error('unexpected')]) {
  const result = response(error);
  assert.equal(result.status, 500);
  assert.equal(result.body.type, 'unknown_error');
  assert.equal(result.body.message, 'An unknown error occurred.');
}
assert.equal(response(databaseError('40001')).status, 409);
console.log('reference stock rejection and unexpected-error regression checks passed');
