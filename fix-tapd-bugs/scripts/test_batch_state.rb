# frozen_string_literal: true
require 'minitest/autorun'
require 'tmpdir'
require_relative 'batch_state'

class BatchStateTest < Minitest::Test
  def setup
    @tmp = Dir.mktmpdir('tapd-journal-test-')
    @repo = File.join(@tmp, 'repo')
    Dir.mkdir(@repo)
    @path = File.join(@tmp, 'private', 'batch.json')
    @sha = 'a' * 40
    @payload = 'b' * 64
  end

  def teardown
    FileUtils.remove_entry(@tmp)
  end

  def call(command, data = {})
    TapdBatchState.run(command, @path, data)
  end

  def start(acceptance = false, ids = %w[1], ui_ids: [])
    call('init', 'repo' => @repo, 'batch_id' => 'test', 'source_head' => @sha,
         'source_fingerprint' => @payload, 'require_acceptance' => acceptance,
         'bugs' => ids.map { |id| {
           'id' => id, 'url' => "https://example.test/#{id}", 'snapshot' => 'v1',
           'ui_bug' => ui_ids.include?(id)
         } })
  end

  def validate(id = '1')
    call('update', 'bug_id' => id, 'status' => 'FIXING')
    verification = %w[tests build static review].to_h { |k| [k, 'passed evidence'] }
    if call('show')['bugs'].find { |bug| bug['id'] == id }['ui_bug']
      path = File.join(@tmp, "ui-#{id}.png")
      File.binwrite(path, "runtime screenshot for #{id}")
      verification['ui_screenshots'] = [{ 'path' => path, 'sha256' => Digest::SHA256.file(path).hexdigest }]
    end
    call('update', 'bug_id' => id, 'status' => 'VALIDATED',
         'verification' => verification)
  end

  def commit(id = '1')
    call('committed', 'bug_id' => id, 'commit_shas' => [@sha])
  end

  def start_sync
    call('sync-start', 'remote' => 'origin', 'remote_ref' => 'refs/heads/develop',
         'source_head' => @sha, 'source_fingerprint' => @payload)
  end

  def sync_receipt(final_sha = @sha)
    {
      'source_head' => final_sha, 'fetched_head' => 'c' * 40, 'remote_head' => final_sha,
      'observed_at' => Time.now.utc.iso8601, 'commit_mapping' => { @sha => final_sha },
      'verification' => %w[tests build static review mapping].to_h { |key| [key, '核验通过'] }
    }
  end

  def freeze_after_push
    start_sync
    call('sync-complete', sync_receipt)
    call('freeze')
  end

  def intent(operation = 'comment')
    call('intent', 'bug_id' => '1', 'operation' => operation, 'snapshot' => 'v1', 'payload_sha256' => @payload)
  end

  def receipt(operation = 'comment')
    call('receipt', 'bug_id' => '1', 'operation' => operation, 'observed' => 'present',
         'payload_sha256' => @payload, 'receipt_id' => 'remote-123')
  end

  def test_acceptance_gate_survives_reload
    start(true)
    validate
    assert_raises(TapdBatchState::Error) { call('check-commit', 'bug_id' => '1') }
    assert_raises(TapdBatchState::Error) { commit }
    assert call('report')['waiting_acceptance']
    call('accepted', 'bug_id' => '1', 'user_confirmed' => true)
    call('check-commit', 'bug_id' => '1')
    commit
    assert_equal [@sha], freeze_after_push['frozen']['commit_shas']
    assert_equal 0o600, File.stat(@path).mode & 0o777
    assert_equal 0o700, File.stat(File.dirname(@path)).mode & 0o777
  end

  def test_new_batch_requires_explicit_ui_classification
    assert_raises(TapdBatchState::Error) do
      call('init', 'repo' => @repo, 'batch_id' => 'test', 'source_head' => @sha,
           'source_fingerprint' => @payload, 'bugs' => [{
             'id' => '1', 'url' => 'https://example.test/1', 'snapshot' => 'v1'
           }])
    end
    assert_raises(TapdBatchState::Error) do
      call('init', 'repo' => @repo, 'batch_id' => 'test', 'source_head' => @sha,
           'source_fingerprint' => @payload, 'bugs' => [{
             'id' => '1', 'url' => 'https://example.test/1', 'snapshot' => 'v1', 'ui_bug' => 'true'
           }])
    end
  end

  def test_ui_bug_requires_real_external_screenshot_with_matching_hash
    start(false, %w[1], ui_ids: %w[1])
    call('update', 'bug_id' => '1', 'status' => 'FIXING')
    verification = %w[tests build static review].to_h { |key| [key, 'passed evidence'] }
    assert_raises(TapdBatchState::Error) do
      call('update', 'bug_id' => '1', 'status' => 'VALIDATED', 'verification' => verification)
    end

    path = File.join(@tmp, 'ui.png')
    File.binwrite(path, 'runtime screenshot')
    verification['ui_screenshots'] = [{ 'path' => path, 'sha256' => '0' * 64 }]
    assert_raises(TapdBatchState::Error) do
      call('update', 'bug_id' => '1', 'status' => 'VALIDATED', 'verification' => verification)
    end

    repository_path = File.join(@repo, 'ui.png')
    File.binwrite(repository_path, 'runtime screenshot')
    verification['ui_screenshots'] = [{
      'path' => repository_path, 'sha256' => Digest::SHA256.file(repository_path).hexdigest
    }]
    assert_raises(TapdBatchState::Error) do
      call('update', 'bug_id' => '1', 'status' => 'VALIDATED', 'verification' => verification)
    end

    verification['ui_screenshots'] = [{ 'path' => path, 'sha256' => Digest::SHA256.file(path).hexdigest }]
    state = call('update', 'bug_id' => '1', 'status' => 'VALIDATED', 'verification' => verification)
    assert_equal File.realpath(path), state['bugs'][0].dig('verification', 'ui_screenshots', 0, 'path')
  end

  def test_ui_bug_requires_tapd_screenshot_receipt_before_resolution
    start(false, %w[1], ui_ids: %w[1])
    validate
    commit
    freeze_after_push
    intent('comment')
    receipt('comment')
    assert_raises(TapdBatchState::Error) { intent('resolve') }
    assert_equal 'PARTIAL', call('report', 'delivery_status' => 'published')['status']
    intent('attachment')
    receipt('attachment')
    intent('resolve')
    receipt('resolve')
    assert_equal 'COMPLETE', call('report', 'delivery_status' => 'published')['status']
  end

  def test_success_subset_remains_partial
    start(false, %w[1 2])
    validate
    commit
    assert_raises(TapdBatchState::Error) { call('freeze') }
    call('update', 'bug_id' => '2', 'status' => 'BLOCKED', 'reason' => 'missing attachment')
    assert_equal ['1'], freeze_after_push['frozen']['bug_ids']
    %w[comment resolve].each { |op| intent(op); receipt(op) }
    assert_equal 'PARTIAL', call('report', 'delivery_status' => 'published')['status']
  end

  def test_uncertain_response_reconciles_without_duplicate
    start
    validate
    commit
    freeze_after_push
    intent
    assert_raises(TapdBatchState::Error) { intent }
    call('reconcile', 'bug_id' => '1', 'operation' => 'comment', 'observed' => 'unknown')
    assert_raises(TapdBatchState::Error) { intent }
    receipt
    assert_raises(TapdBatchState::Error) { intent }
    intent('resolve')
    receipt('resolve')
    assert_equal 'COMPLETE', call('report', 'delivery_status' => 'published')['status']
    assert_equal 'PARTIAL', call('report', 'delivery_status' => 'publication_unknown')['status']
  end

  def test_absence_requires_definitive_reconciliation
    start
    validate
    commit
    freeze_after_push
    intent
    assert_raises(TapdBatchState::Error) do
      call('reconcile', 'bug_id' => '1', 'operation' => 'comment', 'observed' => 'absent')
    end
    call('reconcile', 'bug_id' => '1', 'operation' => 'comment', 'observed' => 'absent', 'definitive' => true)
    intent
    assert_equal 'inflight', call('show')['bugs'][0]['operations']['comment']['status']
  end

  def test_changed_remote_blocks_writes
    start
    validate
    commit
    freeze_after_push
    call('check-snapshot', 'bug_id' => '1', 'snapshot' => 'v2')
    assert_raises(TapdBatchState::Error) { intent }
    assert_equal 'PARTIAL', call('report')['status']
  end

  def test_private_path_cannot_enter_repo_through_symlink
    File.symlink(@repo, File.join(@tmp, 'link'))
    @path = File.join(@tmp, 'link', 'journal.json')
    assert_raises(TapdBatchState::Error) { start }
    refute File.exist?(@path)
  end

  def test_existing_public_parent_is_rejected_without_chmod
    directory = File.dirname(@path)
    Dir.mkdir(directory, 0o755)
    assert_raises(TapdBatchState::Error) { start }
    assert_equal 0o755, File.stat(directory).mode & 0o777
    refute File.exist?(@path)
  end

  def test_multistep_resolution_requires_final_resolution_receipt
    start
    validate
    commit
    freeze_after_push
    %w[comment resolve:start].each { |op| intent(op); receipt(op) }
    assert_equal 'PARTIAL', call('report', 'delivery_status' => 'published')['status']
    intent('resolve')
    receipt('resolve')
    assert_equal 'COMPLETE', call('report', 'delivery_status' => 'published')['status']
  end

  def test_freeze_requires_confirmed_push_and_new_sha_survives_reload
    start
    validate
    commit
    assert_raises(TapdBatchState::Error) { call('freeze') }
    start_sync
    assert_raises(TapdBatchState::Error) { call('freeze') }
    assert_raises(TapdBatchState::Error) { start_sync }
    refute call('report')['pushed']
    new_sha = 'd' * 40
    call('sync-complete', sync_receipt(new_sha))
    frozen = call('freeze')['frozen']
    assert_equal [new_sha], frozen['commit_shas']
    assert_equal new_sha, frozen['source_head']
    assert_equal [new_sha], call('show')['bugs'][0]['commit_shas']
    assert_equal [@sha], call('show')['sync']['before_commits']
    assert call('report')['pushed']
    assert_raises(TapdBatchState::Error) { start_sync }
  end

  def test_wrong_remote_tip_incomplete_mapping_and_missing_checks_do_not_release_gate
    start
    validate
    commit
    start_sync
    [
      sync_receipt.merge('remote_head' => 'e' * 40),
      sync_receipt.merge('commit_mapping' => {}),
      sync_receipt.merge('commit_mapping' => { @sha => 'invalid' }),
      sync_receipt.merge('verification' => { 'tests' => 'passed' })
    ].each do |input|
      assert_raises(TapdBatchState::Error) { call('sync-complete', input) }
      assert_equal 'SYNCING', call('show')['sync']['status']
      assert_equal [@sha], call('show')['bugs'][0]['commit_shas']
      assert_raises(TapdBatchState::Error) { call('freeze') }
    end
  end

  def test_new_sync_invalidates_previous_push_receipt
    start
    validate
    commit
    start_sync
    call('sync-complete', sync_receipt('d' * 40))
    start_sync
    refute call('report')['pushed']
    assert_equal 'PUSHED', call('show')['sync_history'][0]['status']
    assert_raises(TapdBatchState::Error) { call('freeze') }
    call('sync-complete', sync_receipt('e' * 40).merge('commit_mapping' => { 'd' * 40 => 'e' * 40 }))
    assert_equal ['e' * 40], call('freeze')['frozen']['commit_shas']
  end

  def test_shared_commit_mapping_and_reopened_bug_invalidate_sync
    start(false, %w[1 2 3])
    %w[1 2].each { |id| validate(id); commit(id) }
    call('update', 'bug_id' => '3', 'status' => 'BLOCKED', 'reason' => '附件不可读')
    start_sync
    call('sync-complete', sync_receipt('d' * 40))
    assert_equal [['d' * 40], ['d' * 40]], call('show')['bugs'].first(2).map { |bug| bug['commit_shas'] }
    call('update', 'bug_id' => '3', 'status' => 'FIXING')
    refute call('report')['pushed']
    call('update', 'bug_id' => '3', 'status' => 'BLOCKED', 'reason' => '仍不可读')
    assert_raises(TapdBatchState::Error) { call('freeze') }
  end

  def test_legacy_frozen_batch_without_push_receipt_is_partial
    start
    validate
    commit
    freeze_after_push
    %w[comment resolve].each { |op| intent(op); receipt(op) }
    legacy = call('show')
    legacy.delete('sync')
    legacy['schema_version'] = 1
    legacy['bugs'].each { |bug| bug.delete('ui_bug') }
    File.write(@path, JSON.generate(legacy))
    assert_equal 'PARTIAL', call('report', 'delivery_status' => 'published')['status']
    refute call('report')['pushed']
  end
end
