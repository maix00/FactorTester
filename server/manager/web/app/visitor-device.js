(() => {
  const DATABASE = "factortester-device";
  const STORE = "credentials";
  const pending = new Map();

  function openDatabase() {
    return new Promise((resolve, reject) => {
      if (!window.indexedDB) {
        reject(new Error("browser device storage is unavailable"));
        return;
      }
      const request = indexedDB.open(DATABASE, 1);
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains(STORE)) {
          request.result.createObjectStore(STORE, {keyPath: "device_id"});
        }
      };
      request.onsuccess = () => {
        const database = request.result;
        database.onversionchange = () => database.close();
        resolve(database);
      };
      request.onerror = () => reject(request.error || new Error("browser device storage is unavailable"));
    });
  }

  async function listCredentials() {
    const database = await openDatabase();
    return new Promise((resolve, reject) => {
      const values = [];
      const transaction = database.transaction(STORE, "readonly");
      const finish = (error, result) => {
        database.close();
        if (error) reject(error); else resolve(result);
      };
      transaction.oncomplete = () => finish(null, values);
      transaction.onerror = () => finish(transaction.error || new Error("browser device storage is unavailable"));
      transaction.onabort = () => finish(transaction.error || new Error("browser device storage is unavailable"));
      const request = transaction.objectStore(STORE).openCursor();
      request.onsuccess = event => {
        const cursor = event.target.result;
        if (cursor) {
          values.push(cursor.value);
          cursor.continue();
        }
      };
      request.onerror = () => finish(request.error || new Error("browser device storage is unavailable"));
    });
  }

  async function saveCredential(value) {
    const database = await openDatabase();
    return new Promise((resolve, reject) => {
      const transaction = database.transaction(STORE, "readwrite");
      const finish = error => {
        database.close();
        if (error) reject(error); else resolve();
      };
      transaction.oncomplete = () => finish();
      transaction.onerror = () => finish(transaction.error || new Error("browser device storage failed"));
      transaction.onabort = () => finish(transaction.error || new Error("browser device storage failed"));
      const request = transaction.objectStore(STORE).put(value);
      request.onerror = () => finish(request.error || new Error("browser device storage failed"));
    });
  }

  function newDeviceID() {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();
    const bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    return [...bytes].map(value => value.toString(16).padStart(2, "0")).join("");
  }

  async function enroll(context, session) {
    const username = String(session?.username || "").trim();
    if (!username || !session?.visitor_login) return;
    if (!window.crypto?.subtle) throw new Error("browser device key generation is unavailable");
    const existing = (await listCredentials()).find(value => (
      String(value?.username || "") === username && value.private_key
    ));
    if (existing) return existing;

    const pair = await window.crypto.subtle.generateKey(
      {name: "ECDSA", namedCurve: "P-256"},
      false,
      ["sign", "verify"],
    );
    const publicKey = await window.crypto.subtle.exportKey("jwk", pair.publicKey);
    const deviceID = newDeviceID();
    const response = await context.api("/api/devices/enroll", {
      method: "POST",
      body: JSON.stringify({
        device_id: deviceID,
        public_key: publicKey,
        device_name: "Allowlisted browser",
      }),
    });
    await saveCredential({
      device_id: deviceID,
      username,
      public_key: publicKey,
      private_key: pair.privateKey,
    });
    return response.device || {device_id: deviceID, username};
  }

  function ensureForSession(context, session) {
    const username = String(session?.username || "").trim();
    if (!username || !session?.visitor_login) return Promise.resolve(null);
    if (!pending.has(username)) {
      const task = enroll(context, session).finally(() => pending.delete(username));
      pending.set(username, task);
    }
    return pending.get(username);
  }

  window.FTVisitorDevice = Object.freeze({ensureForSession});
})();
