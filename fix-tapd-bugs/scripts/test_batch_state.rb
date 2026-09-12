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

  def start(acceptance = false, ids = %w[1])
    call('init', 'repo' => @repo, 'batch_id' => 'test', 'source_head' => @sha,
         'source_fingerprint' => @payload, 'require_acceptance' => acceptance,
         'bugs' => ids.map { |id| { 'id' => id, 'url' => "https://example.test/#{id}", 'snapshot' => 'v1' } })
  end

  def validate(id = '1')
    call('update', 'bug_id' => id, 'status' => 'FIXING')
    call('update', 'bug_id' => id, 'status' => 'VALIDATED',
         'verification' => %w[tests build static review].to_h { |k| [k, 'passed evidence'] })
  end

  def commit(id = '1')
    call('committed', 'bug_id' => id, 'commit_shas' => [@sha])
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
    assert_equal [@sha], call('freeze')['frozen']['commit_shas']
    assert_equal 0o600, File.stat(@path).mode & 0o777
    assert_equal 0o700, File.stat(File.dirname(@path)).mode & 0o777
  end

  def test_success_subset_remains_partial
    start(false, %w[1 2])
    validate
    commit
    assert_raises(TapdBatchState::Error) { call('freeze') }
    call('update', 'bug_id' => '2', 'status' => 'BLOCKED', 'reason' => 'missing attachment')
    assert_equal ['1'], call('freeze')['frozen']['bug_ids']
    %w[comment resolve].each { |op| intent(op); receipt(op) }
    assert_equal 'PARTIAL', call('report', 'delivery_status' => 'published')['status']
  end

  def test_uncertain_response_reconciles_without_duplicate
    start
    validate
    commit
    call('freeze')
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
    call('freeze')
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
    call('freeze')
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
    call('freeze')
    %w[comment resolve:start].each { |op| intent(op); receipt(op) }
    assert_equal 'PARTIAL', call('report', 'delivery_status' => 'published')['status']
    intent('resolve')
    receipt('resolve')
    assert_equal 'COMPLETE', call('report', 'delivery_status' => 'published')['status']
  end
end
