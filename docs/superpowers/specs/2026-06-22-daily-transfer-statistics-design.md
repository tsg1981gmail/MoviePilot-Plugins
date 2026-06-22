# Daily Transfer Statistics Design

## Background

The `brushflowlowfreq` plugin already records cumulative uploaded and downloaded bytes for each managed torrent task during the periodic `check()` flow. The current aggregate statistic stored under `statistic` only exposes total and active uploaded/downloaded amounts. It does not preserve daily upload/download increments, so users cannot see how much traffic the plugin contributed today or on previous days.

The requested feature is a daily upload/download statistic inside the plugin, with a history view. The statistic must only include torrent tasks managed by this plugin. It must not include unrelated downloader tasks.

## Goals

1. Track daily uploaded and downloaded increments for plugin-managed torrent tasks.
2. Show today's uploaded/downloaded amount in the plugin data page.
3. Let users view historical daily records from the plugin data page.
4. Avoid counting historical cumulative traffic as today's traffic after upgrade.
5. Keep the implementation small and compatible with the existing plugin data model.

## Non-Goals

- Do not count global downloader traffic.
- Do not count unmanaged downloader tasks.
- Do not add per-site or per-torrent daily drilldown in the first version.
- Do not add export, charts, or configurable retention in the first version.
- Do not change existing total statistic semantics.

## Recommended Approach

Use cumulative counter differencing during the existing `check()` flow.

Each managed torrent task already receives current cumulative `uploaded` and `downloaded` values from the downloader. The daily statistics module will compare those values against per-task daily statistic baselines. Valid positive deltas will be added to the current local date's daily record.

This approach is preferred because it uses data the plugin already owns, preserves the "plugin-managed tasks only" scope, and avoids relying on downloader-wide transfer counters that would include unrelated tasks.

## Data Model

Add a new persisted plugin data key:

```json
{
  "daily_statistic": {
    "2026-06-22": {
      "date": "2026-06-22",
      "uploaded": 123456789,
      "downloaded": 987654321,
      "task_count": 5,
      "updated_at": 1782067200
    }
  }
}
```

Daily record fields:

- `date`: local date in `YYYY-MM-DD` format.
- `uploaded`: bytes uploaded during that date by plugin-managed tasks.
- `downloaded`: bytes downloaded during that date by plugin-managed tasks.
- `task_count`: number of distinct managed tasks that contributed a valid positive delta on that date.
- `updated_at`: Unix timestamp of the most recent update.

Add per-task baseline fields to managed torrent task dictionaries:

```json
{
  "daily_stat_last_date": "2026-06-22",
  "daily_stat_last_uploaded": 123456789,
  "daily_stat_last_downloaded": 987654321
}
```

These fields are only accounting baselines. They do not replace the existing `uploaded`, `downloaded`, or `statistic` fields.

## Date and Timezone

Daily buckets use the MoviePilot timezone. The implementation should prefer `settings.TZ` when available and fall back to the process local timezone if timezone creation fails.

The date key is generated at accounting time, not from torrent publish time or add time.

## Accounting Flow

The accounting flow runs after downloader state has been merged into `torrent_tasks` in `check()`.

For each plugin-managed task:

1. Skip tasks with invalid or missing cumulative `uploaded` or `downloaded` values.
2. Read the per-task baseline fields.
3. If no baseline exists, initialize the baseline to the current cumulative values and do not add any daily traffic.
4. If the current local date differs from `daily_stat_last_date`, reset the baseline date to the current date and use the previous cumulative values as the comparison base. This allows transfer since the last check to be counted into the new day without importing all historical traffic.
5. Compute:

   ```text
   upload_delta = current_uploaded - daily_stat_last_uploaded
   download_delta = current_downloaded - daily_stat_last_downloaded
   ```

6. If either delta is negative, treat the task as a counter reset. Refresh its baseline to the current cumulative values and skip adding traffic for this task in this check.
7. Add positive deltas to the current date's `daily_statistic` record.
8. If either delta is positive, count the task once in that day's contributing task set for the current accounting run.
9. Update the task baseline to the current cumulative values and current date.
10. Save `daily_statistic` and `torrents` with the existing persistence helpers.

The first check after upgrade only establishes baselines. It must not count each task's existing cumulative uploaded/downloaded amount as today's traffic.

## History Display

Update `get_page()` to include a daily traffic section above or near the existing torrent detail table.

The section should show:

- Today's uploaded amount.
- Today's downloaded amount.
- A table of recent daily records.

Recommended first-version table columns:

- Date
- Uploaded
- Downloaded
- Contributing tasks
- Updated at

The first version should render the recent history directly in the data page instead of requiring an API endpoint. This follows the current plugin pattern, where `get_page()` returns Vuetify component JSON and `get_api()` is unused.

Sort history by date descending. Show a bounded recent list, such as the latest 30 records, to keep the page readable. Keep all persisted records unless a future retention setting is added.

If there are no daily records, show a compact empty state such as `暂无每日流量统计`.

## Dashboard

The first version does not need to change `get_dashboard()`. The daily section in `get_page()` is enough to satisfy viewing today's amount and historical records.

If a later iteration needs dashboard support, it can reuse the same `daily_statistic` data and add today's upload/download cards next to the existing total cards.

## Clear Data Behavior

`__clear_tasks()` should clear the new `daily_statistic` data key together with existing plugin data:

- `torrents`
- `archived`
- `unmanaged`
- `statistic`
- `daily_statistic`

This keeps the existing "clear statistics" action semantically complete.

## Error Handling

Invalid task counters should not break the `check()` flow.

Rules:

- Missing or non-numeric uploaded/downloaded values: skip daily accounting for that task.
- Negative deltas: refresh baseline and skip that task for the current check.
- Malformed `daily_statistic`: treat it as empty and rebuild from future deltas.
- Timezone failures: fall back to a plain local date and log a warning if useful.

## Implementation Units

Keep the change inside `plugins.v2/brushflowlowfreq/__init__.py` unless tests reveal a need for helpers.

Suggested private methods:

- `__get_daily_statistic_info() -> Dict[str, dict]`
- `__get_daily_stat_date(now: Optional[datetime] = None) -> str`
- `__update_daily_transfer_statistics(torrent_tasks: Dict[str, dict]) -> None`
- `__get_daily_transfer_elements() -> List[dict]`

The statistic update method should be mostly pure accounting over dictionaries, so unit tests can call it directly through name-mangled access without needing a real downloader.

## Integration Points

1. New managed torrent tasks can omit baseline fields. The first `check()` initializes them.
2. Existing managed tasks from older versions also initialize baselines on first check.
3. `check()` calls `__update_daily_transfer_statistics(torrent_tasks)` after `__update_torrent_tasks_state(...)` and before final persistence.
4. `get_page()` renders daily history from `daily_statistic`.
5. `__clear_tasks()` clears `daily_statistic`.

## Tests

Add focused tests in `tests/test_brushflowlowfreq_features.py`:

1. First daily accounting call initializes baselines and records no traffic.
2. A later call on the same date records uploaded/downloaded deltas.
3. Multiple tasks on the same date aggregate into one record.
4. Negative uploaded/downloaded deltas refresh baselines and do not subtract from the daily record.
5. A date change creates or updates the new date's record without importing all historical traffic.
6. `__clear_tasks()` clears `daily_statistic`.
7. `get_page()` includes the daily history section when records exist.
8. `get_page()` shows a daily-statistic empty state when torrent task data exists but no daily records exist.

## Risks and Tradeoffs

| Risk | Mitigation |
| --- | --- |
| First day after upgrade misses traffic before the first post-upgrade check | Expected and safer than overcounting old cumulative totals |
| Transfer across midnight is assigned to the date of the next check | Acceptable for a 150-second check interval; exact midnight splitting is unnecessary for this plugin |
| Downloader counter resets could lose one interval | Negative deltas are skipped to avoid corrupting daily totals |
| History grows forever | Store compact daily records; add retention later only if needed |
| UI becomes too dense | Show only recent records in the page while retaining all stored records |

## Acceptance Criteria

- Daily statistics only include plugin-managed torrent tasks.
- Existing cumulative totals continue to work as before.
- First check after upgrade does not add old cumulative uploaded/downloaded values to today.
- Same-day positive deltas are accumulated under the current local date.
- Historical daily records are visible from the plugin data page.
- Clearing plugin statistics clears daily history too.
- Unit tests cover the core accounting and page rendering behavior.
