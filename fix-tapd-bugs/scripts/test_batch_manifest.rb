require 'minitest/autorun'
require 'tmpdir'
require 'fileutils'
require 'json'
require 'open3'

class BatchManifestTest < Minitest::Test
  def setup
    @tmp = Dir.mktmpdir('batch-manifest-test')
    @repo = File.join(@tmp, 'repo')
    FileUtils.mkdir_p(@repo)
    git('init', '-q')
    git('config', 'user.email', 'test@example.invalid')
    git('config', 'user.name', 'Test')
    File.write(File.join(@repo, 'a'), 'base')
    git('add', '.')
    git('commit', '-qm', 'fix: fixture')
  end

  def teardown
    FileUtils.remove_entry(@tmp)
  end

  def git(*args)
    out, code = Open3.capture2e('git', '-C', @repo, *args)
    raise out unless code.success?
    out.strip
  end

  def freeze_batch(name, out: File.join(@tmp, name, 'manifest.json'))
    output, status = Open3.capture2e('ruby', File.join(__dir__, 'batch_manifest.rb'),
      '--repo', @repo, '--batch-id', name, '--out', out,
      '--state-path', File.join(@tmp, name, 'delivery.json'),
      '--bug', '42=https://example.invalid/42', '--bug-commit', '42=HEAD', '--commit', 'HEAD')
    [output, status, out]
  end

  def test_resolves_head_and_bug_mapping
    output, code, path = freeze_batch('one')
    assert code.success?, output
    doc = JSON.parse(File.read(path))
    assert_equal [git('rev-parse', 'HEAD')], doc['commit_shas']
    assert_equal doc['commit_shas'], doc['bugs'][0]['commit_shas']
    assert_equal 0o600, File.stat(path).mode & 0o777
    output, code = freeze_batch('one')
    refute code.success?, output
  end

  def test_staged_changes_change_fingerprint
    File.write(File.join(@repo, 'a'), 'first')
    git('add', '.')
    _, code, first = freeze_batch('first')
    assert code.success?
    File.write(File.join(@repo, 'a'), 'second')
    git('add', '.')
    _, code, second = freeze_batch('second')
    assert code.success?
    refute_equal JSON.parse(File.read(first))['source_fingerprint'], JSON.parse(File.read(second))['source_fingerprint']
  end

  def test_symlink_into_repository_is_rejected
    File.symlink(@repo, File.join(@tmp, 'alias'))
    output, code = freeze_batch('escape', out: File.join(@tmp, 'alias', 'manifest.json'))
    refute code.success?, output
    refute File.exist?(File.join(@repo, 'manifest.json'))
  end

  def test_related_bugs_share_commit_and_unrelated_bug_has_own_commit
    related_sha = git('rev-parse', 'HEAD')
    File.write(File.join(@repo, 'unrelated'), 'different root cause')
    git('add', 'unrelated')
    git('commit', '-qm', 'fix: unrelated fixture')
    unrelated_sha = git('rev-parse', 'HEAD')
    path = File.join(@tmp, 'grouped', 'manifest.json')
    args = ['ruby', File.join(__dir__, 'batch_manifest.rb'), '--repo', @repo,
            '--batch-id', 'grouped', '--out', path,
            '--state-path', File.join(@tmp, 'grouped', 'delivery.json'),
            '--commit', related_sha, '--commit', unrelated_sha]
    { '41' => related_sha, '42' => related_sha, '43' => unrelated_sha }.each do |id, sha|
      args.concat(['--bug', "#{id}=https://example.invalid/#{id}", '--bug-commit', "#{id}=#{sha}"])
    end
    output, code = Open3.capture2e(*args)
    assert code.success?, output
    manifest = JSON.parse(File.read(path))
    mapping = manifest['bugs'].to_h { |bug| [bug['id'], bug['commit_shas']] }
    assert_equal [related_sha], mapping['41']
    assert_equal mapping['41'], mapping['42']
    assert_equal [unrelated_sha], mapping['43']
    assert_equal [related_sha, unrelated_sha], manifest['commit_shas']
  end

  def test_isolated_worktree_preserves_dirty_source
    git('update-ref', 'refs/remotes/origin/fixture', 'HEAD')
    File.write(File.join(@repo, 'a'), 'user dirty tracked content')
    File.write(File.join(@repo, 'private-note'), 'user untracked content')
    before = git('status', '--porcelain=v1')
    output, code = Open3.capture2e({ 'PATH' => '/usr/bin:/bin' }, 'bash',
      File.join(__dir__, 'worktree.sh'), "--repo=#{@repo}", 'create',
      'codex/isolated-fixture', '--base=fixture')
    assert code.success?, output
    worktree = File.join(@tmp, 'codex-isolated-fixture')
    assert File.file?(File.join(worktree, '.git'))
    assert_equal 'base', File.read(File.join(worktree, 'a'))
    refute File.exist?(File.join(worktree, 'private-note'))
    assert_equal 'user dirty tracked content', File.read(File.join(@repo, 'a'))
    assert_equal 'user untracked content', File.read(File.join(@repo, 'private-note'))
    assert_equal before, git('status', '--porcelain=v1')
    clean, status = Open3.capture2e('git', '-C', worktree, 'status', '--porcelain=v1')
    assert status.success?, clean
    assert_empty clean
  end
end
