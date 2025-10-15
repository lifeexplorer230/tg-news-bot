# Security Policy

## Reporting Security Vulnerabilities

If you discover a security vulnerability, please email the maintainer directly instead of using the issue tracker.

## Security Updates

### 2025-10-15: Fixed RCE vulnerability in pickle deserialization

**Severity:** 🔴 CRITICAL (RCE - Remote Code Execution)

#### Vulnerability Description

Previous versions used `pickle.dumps()`/`pickle.loads()` to serialize/deserialize numpy embeddings in the database. This created a **critical RCE vulnerability**:

- **Attack vector:** Malicious database file (e.g., via `restore_db.sh`)
- **Impact:** Arbitrary code execution when bot loads embeddings
- **CVSS Score:** 9.8 (Critical)

**Vulnerable code:**
```python
# DANGEROUS! 🔴
embedding_bytes = pickle.dumps(embedding)        # Save
embedding = pickle.loads(row[1])  # nosec B301  # Load - RCE!
```

**Example exploit:**
```python
import pickle
import os

class Exploit:
    def __reduce__(self):
        return (os.system, ('malicious_command',))

# When pickle.loads() is called - code executes! 💀
```

#### Fix

**Version:** 2.2.1+
**Commit:** [security/fix-pickle-deserialization]

Replaced pickle with **safe numpy serialization**:

```python
# SAFE! ✅
# Save:
buffer = io.BytesIO()
np.save(buffer, embedding, allow_pickle=False)
embedding_bytes = buffer.getvalue()

# Load:
buffer = io.BytesIO(row[1])
embedding = np.load(buffer, allow_pickle=False)
```

**Key changes:**
- ✅ Removed `pickle` import from `database/db.py`
- ✅ Replaced with `numpy.save()`/`numpy.load()` with `allow_pickle=False`
- ✅ Added migration script: `scripts/migrate_pickle_to_numpy.py`
- ✅ All 103 tests pass with new implementation

#### Migration for Existing Databases

If you have existing database with pickle-serialized embeddings:

```bash
# 1. Create backup
cp ./data/marketplace_news.db ./data/marketplace_news.db.backup

# 2. Dry-run (check without changes)
python scripts/migrate_pickle_to_numpy.py --db ./data/marketplace_news.db

# 3. Apply migration
python scripts/migrate_pickle_to_numpy.py --db ./data/marketplace_news.db --apply
```

**IMPORTANT:** Run migration script **ONLY ONCE** after updating the code!

#### Impact

- ✅ **No functionality changes** - embeddings work exactly the same
- ✅ **Performance:** No measurable difference
- ✅ **Compatibility:** Existing databases need one-time migration
- ✅ **Security:** RCE vulnerability completely eliminated

## Best Practices

1. **Never restore databases from untrusted sources**
2. **Always validate backup sources** before running `restore_db.sh`
3. **Keep dependencies updated** - run `pip install -U -r requirements.txt` regularly
4. **Review security updates** in CHANGELOG.md

## Secure Configuration

- Store API keys in environment variables (not in code)
- Use restricted file permissions for database: `chmod 600 data/*.db`
- Run bot with minimal privileges (non-root user)
- Enable logging for security monitoring

## Dependencies Security

We use:
- `bandit` - Python security linter
- `safety` - dependency vulnerability scanner
- GitHub Dependabot - automated security updates

To check for vulnerabilities:
```bash
pip install bandit safety
bandit -r . -ll
safety check
```

## Changelog of Security Fixes

- **2025-10-15:** Fixed pickle RCE vulnerability (CRITICAL)
