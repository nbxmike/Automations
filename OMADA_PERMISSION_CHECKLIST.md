# Omada Site Permission and Site Association Verification

Use this sequence to confirm whether the Omada account is actually associated with a site and whether the API is returning site records for the logged-in user.

## 1. Log in and capture the session

```bash
curl -k -i -c /tmp/omada.cookies \
  -H 'Content-Type: application/json' \
  -d '{"username":"YOUR_USERNAME","password":"YOUR_PASSWORD"}' \
  'https://172.24.32.241:8043/api/v2/login'
```

Look for:

- HTTP 200
- JSON response with `errorCode: 0`
- token value in `result.token`
- `omadacId` in the JSON response

Example:

```json
{"errorCode":0,"msg":"Log in successfully.","result":{"omadacId":"4be285e523814010fde7f162eaf3ec6f","token":"..."}}
```

The `omadacId` is the controller instance ID. It is not the site ID.

---

## 2. Capture the CSRF token from the login response or headers

If the controller sends a CSRF token or a header for the session, capture it. If it is not directly exposed in the JSON, inspect the response headers for a relevant `Csrf-Token` header:

```bash
curl -k -i -c /tmp/omada.cookies \
  -H 'Content-Type: application/json' \
  -d '{"username":"YOUR_USERNAME","password":"YOUR_PASSWORD"}' \
  'https://172.24.32.241:8043/api/v2/login' | sed -n '1,200p'
```

If the token is present, use it in the next requests:

```bash
export OMADA_CSRF='YOUR_CSRF_TOKEN'
export OMADA_OMADAC_ID='4be285e523814010fde7f162eaf3ec6f'
```

---

## 3. Query the site list using the controller-specific path

This is the path that worked in your tests:

```bash
curl -k -i -b /tmp/omada.cookies \
  -H "Csrf-Token: $OMADA_CSRF" \
  "https://172.24.32.241:8043/$OMADA_OMADAC_ID/api/v2/sites?currentPage=1&pageSize=100"
```

Look for:

- HTTP 200
- `content-type: application/json`
- a JSON structure containing `result.data`

If the response is:

```json
{"result":{"data":[],"siteStat":{"total":1,...}}}
```

then the controller is authenticated but the account is not returning any site records.

This means the account is not associated with a visible site in that controller session.

---

## 4. Inspect the payload closely

If the response returns `data: []`, this is the critical clue. It indicates:

- login succeeded
- session is valid
- but the account has no assigned site visible to the API

You can inspect it more cleanly with:

```bash
curl -k -s -b /tmp/omada.cookies \
  -H "Csrf-Token: $OMADA_CSRF" \
  "https://172.24.32.241:8043/$OMADA_OMADAC_ID/api/v2/sites?currentPage=1&pageSize=100" | python3 -m json.tool
```

This will pretty-print the JSON if it is valid JSON.

---

## 5. Test the site route against a known site ID if one is visible

If a site ID does appear in any site object, query the clients endpoint:

```bash
curl -k -i -b /tmp/omada.cookies \
  -H "Csrf-Token: $OMADA_CSRF" \
  "https://172.24.32.241:8043/$OMADA_OMADAC_ID/api/v2/sites/<SITE_ID>/clients"
```

If you do not have a visible site ID because the site list is empty, this remains a permissions or association problem.

---

## 6. Check whether the account is site-bound in the Omada UI

In the Omada controller web UI, verify:

- the account is a full admin or site admin
- the account is assigned to the site
- the site is active and not archived
- the account has not been restricted to a different tenant/site
- the account has permission to manage WLAN and clients

If the UI shows the site but the API returns empty `data`, the account/site mapping is inconsistent.

---

## 7. Test with the normal admin account, not a service account

Run the same sequence using the normal admin account:

```bash
curl -k -i -c /tmp/omada_admin.cookies \
  -H 'Content-Type: application/json' \
  -d '{"username":"ADMIN_USERNAME","password":"ADMIN_PASSWORD"}' \
  'https://172.24.32.241:8043/api/v2/login'
```

Then query:

```bash
curl -k -s -b /tmp/omada_admin.cookies \
  -H "Csrf-Token: ADMIN_CSRF_TOKEN" \
  "https://172.24.32.241:8043/$OMADA_OMADAC_ID/api/v2/sites?currentPage=1&pageSize=100" | python3 -m json.tool
```

If the admin account still shows `data: []`, then the issue is likely at the controller deployment level rather than the account configuration.

---

## 8. Interpret the result

### Good result

```json
{"result":{"data":[{ "siteId": "...", "name": "..." }]}}
```

This means the account is associated with a site and the controller is exposing the site API correctly.

### Problem result

```json
{"result":{"data":[],"siteStat":{"total":1,...}}}
```

This means the controller accepted the login but did not return any site metadata to the session. This points to:

- permission mismatch
- account not associated with the site
- stale or inconsistent site assignment
- controller deployment/API issue

---

## 9. Final decision

If both the admin account and a dedicated API account return empty site lists, stop debugging the script and move to the native Omada controller installation path. The API contract is not exposing the site data correctly enough for the script to function.
