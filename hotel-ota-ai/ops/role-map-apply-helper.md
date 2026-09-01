# Private Role-Map Apply Helper Contract

The role-map apply helper is a server-private, root-owned tool. It is not
included in the deployment package and is not callable by Feishu, Gateway,
plugin, or workspace runtime code.

Gateway MUST NOT write `/etc/hotel-ota-ai/feishu-role-map.json`. An approved
role-membership request only creates a pending queue record with principal ids,
hotel id, and role operation. A maintenance operator exports that request to a
private candidate file and invokes the helper during an approved window.

The helper must:

1. Accept only a fixed private candidate directory and reject symlinks, hard
   links, non-regular files, oversized files, and arbitrary paths.
2. Validate the V3 allowlisted schema, canonical identity uniqueness, tenant
   memberships, group bindings, and an optional expected current-file hash.
3. Create a root-only versioned backup, write a same-directory temporary file,
   fsync content, set `root:openclaw-config` with mode `0640`, perform atomic rename,
   and fsync the directory.
4. Record only time, caller, old/new file hashes, role counts, request id, and
   outcome. It must never log identities or role-map content.
5. Support dry-run validation before mutation and leave Gateway running; the
   plugin reloads the file per request, so successful atomic replacement needs
   no Gateway restart.

Rollback restores the latest root-only backup after preserving the failing file
hash and the helper audit result. It must not overwrite any other private
configuration.
