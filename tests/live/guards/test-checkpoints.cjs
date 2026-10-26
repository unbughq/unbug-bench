// Run from the pinned Medusa runtime; optional argument is the compiled reference module.
const assert = require('node:assert/strict');
const path = require('node:path');
const { setTimeout: delay } = require('node:timers/promises');
const { DistributedTransaction, TransactionOrchestrator } = require('@medusajs/framework/orchestration');
const { InMemoryDistributedTransactionStorage } = require(path.join(
  path.dirname(require.resolve('@medusajs/workflow-engine-inmemory')), 'utils/workflow-orchestrator-storage.js'));

async function main() {
  if (process.argv[2]) require(path.resolve(process.argv[2]));
  const rows = new Map();
  // The real in-memory workflow store persists to a slow database. Its per-key lock
  // rejects concurrent saves; real saveCheckpoint retries and merges those saves.
  const store = new InMemoryDistributedTransactionStorage({ logger: console,
    workflowExecutionService: {
      async list({ workflow_id, transaction_id }) {
        const row = rows.get(workflow_id + ':' + transaction_id);
        return row ? [structuredClone(row)] : [];
      },
      async upsert(values) {
        await delay(150);
        for (const row of values) rows.set(row.workflow_id + ':' + row.transaction_id, structuredClone(row));
      },
      async delete() {},
    },
  });
  DistributedTransaction.setStorage(store);
  let orderLive = false;
  const events = [];
  const orchestrator = new TransactionOrchestrator({ id: 'g5-checkpoint-regression', options: { store: true },
    definition: { action: 'create-orders', next: [
      { action: 'create-remote-links', store: true },
      { action: 'update-cart', store: true },
      { action: 'reserve-inventory', store: true },
      { action: 'register-usage', store: true },
      { action: 'emit-event', store: true },
    ] },
  });
  const transaction = await orchestrator.beginTransaction({ transactionId: 'g5-public-fixture', handler: async (action, type) => {
    events.push(type + ':' + action);
    if (action === 'create-orders') orderLive = type === 'invoke';
    if (action === 'reserve-inventory' && type === 'invoke') {
      await delay(10);
      throw new Error('Insufficient stock for reservation');
    }
    return {};
  } });
  let error;
  const random = Math.random;
  Math.random = () => 0; // Fixed retry backoff makes the collision repeatable.
  try { await orchestrator.resume(transaction); } catch (e) { error = e; }
  finally { Math.random = random; await store.onApplicationShutdown(); }
  assert.equal(error, undefined, error?.stack);
  assert.equal(orderLive, false, 'Rejected reservation must compensate the previously committed order');
  assert(events.includes('compensate:create-orders'));
  assert(transaction.getErrors().some(e => e.error.message.includes('Insufficient stock')));
  console.log('parallel checkpoint contention preserves stock refusal and compensates the order');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
