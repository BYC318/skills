#!/usr/bin/env ruby
# frozen_string_literal: true

require 'json'
require 'fileutils'
require 'optparse'
require 'digest'
require 'time'

# Local journal only: callers execute and re-read remote operations themselves.
module TapdBatchState
  class Error < StandardError; end
  module_function

  def canonical(path)
    return File.realpath(path) if File.exist?(path) || File.symlink?(path)
    File.join(canonical(File.dirname(path)), File.basename(path))
  end

  def run(command, path, input)
    raise Error, 'state path must be absolute' unless path.start_with?('/')
    path = canonical(path)
    raise Error, 'use a separate batch journal, not delivery.json' if File.basename(path) == 'delivery.json'
    if command == 'init'
      repo = File.realpath(input.fetch('repo'))
      raise Error, 'state must be outside repository' if path == repo || path.start_with?(repo + '/')
      directory = File.dirname(path)
      FileUtils.mkdir_p(directory, mode: 0o700) unless File.directory?(directory)
      metadata = File.stat(directory)
      raise Error, 'state directory must be owned by current user with mode 0700' unless metadata.uid == Process.uid && metadata.mode & 0o777 == 0o700
    end
    File.open(path + '.lock', File::RDWR | File::CREAT, 0o600) do |lock|
      lock.flock(File::LOCK_EX)
      state = File.exist?(path) ? JSON.parse(File.read(path)) : nil
      if command == 'init'
        raise Error, 'batch already exists' if state
        ids = input.fetch('bugs').map { |b| b.fetch('id').to_s }
        raise Error, 'bugs must be nonempty and unique' if ids.empty? || ids.uniq != ids
        state = {
          'schema_version' => 1, 'batch_id' => input.fetch('batch_id'),
          'repo' => repo, 'source_head' => input.fetch('source_head'),
          'source_fingerprint' => input.fetch('source_fingerprint'),
          'initial_changes' => input.fetch('initial_changes', []),
          'require_acceptance' => input.fetch('require_acceptance', false),
          'bugs' => input.fetch('bugs').map { |b| {
            'id' => b.fetch('id').to_s, 'url' => b.fetch('url'),
            'snapshot' => b.fetch('snapshot'), 'status' => 'DISCOVERED',
            'accepted' => false, 'commit_shas' => [], 'operations' => {}
          } }
        }
      else
        raise Error, 'batch does not exist' unless state
        mutate(state, command, input)
      end
      unless %w[show report check-commit].include?(command)
        state['updated_at'] = Time.now.utc.iso8601
        temp = path + ".tmp-#{Process.pid}"
        begin
          File.open(temp, File::WRONLY | File::CREAT | File::EXCL, 0o600) do |f|
            f.write(JSON.pretty_generate(state) + "\n")
            f.flush
            f.fsync
          end
          File.rename(temp, path)
        ensure
          File.unlink(temp) if File.exist?(temp)
        end
      end
      command == 'report' ? report(state, input) : state
    end
  end

  def mutate(state, command, input)
    return if %w[show report].include?(command)
    if command == 'freeze'
      raise Error, 'already frozen' if state['frozen']
      raise Error, 'all bugs must be attempted' if state['bugs'].any? { |b| !%w[COMMITTED BLOCKED].include?(b['status']) }
      successful = state['bugs'].select { |b| b['status'] == 'COMMITTED' }
      raise Error, 'no successful bugs' if successful.empty?
      state['frozen'] = { 'bug_ids' => successful.map { |b| b['id'] },
                          'commit_shas' => successful.flat_map { |b| b['commit_shas'] }.uniq }
      return
    end
    bug = state['bugs'].find { |b| b['id'] == input.fetch('bug_id').to_s }
    raise Error, 'unknown bug' unless bug
    if command == 'check-commit'
      raise Error, 'batch already frozen' if state['frozen']
      raise Error, 'bug must be validated' unless bug['status'] == 'VALIDATED'
      raise Error, 'WAITING_ACCEPTANCE' if state['require_acceptance'] && !bug['accepted']
      return
    end
    if %w[update accepted committed].include?(command)
      raise Error, 'frozen bugs cannot be changed' if state['frozen']
      case command
      when 'update'
        next_status = input.fetch('status')
        allowed = { 'DISCOVERED' => %w[FIXING BLOCKED], 'FIXING' => %w[VALIDATED BLOCKED],
                    'VALIDATED' => %w[FIXING BLOCKED], 'BLOCKED' => %w[FIXING] }
        raise Error, 'invalid status transition' unless allowed.fetch(bug['status'], []).include?(next_status)
        if next_status == 'VALIDATED'
          checks = input.fetch('verification')
          raise Error, 'tests/build/static/review evidence required' unless %w[tests build static review].all? { |key| checks[key].is_a?(String) && !checks[key].strip.empty? }
          bug['verification'] = checks.slice('tests', 'build', 'static', 'review', 'residual_risks')
        end
        bug['accepted'] = false
        bug['status'] = next_status
        bug['reason'] = input.fetch('reason') if next_status == 'BLOCKED'
      when 'accepted'
        raise Error, 'acceptance requires validated bug and user confirmation' unless bug['status'] == 'VALIDATED' && input['user_confirmed'] == true
        bug['accepted'] = true
      when 'committed'
        raise Error, 'bug must be validated' unless bug['status'] == 'VALIDATED'
        raise Error, 'WAITING_ACCEPTANCE' if state['require_acceptance'] && !bug['accepted']
        shas = input.fetch('commit_shas')
        raise Error, 'full commit SHAs required' unless shas.is_a?(Array) && !shas.empty? && shas.all? { |s| s.match?(/\A[0-9a-f]{40}\z/) }
        bug['commit_shas'] = shas.uniq
        bug['status'] = 'COMMITTED'
      end
      return
    end
    raise Error, 'bug is not in frozen successful subset' unless state.fetch('frozen', {}).fetch('bug_ids', []).include?(bug['id'])
    if command == 'check-snapshot'
      if input.fetch('snapshot') != bug['snapshot']
        bug['remote_changed'] = true
        bug['remote_reason'] = 'critical fields changed; do not write'
      end
      return
    end
    key = input.fetch('operation')
    raise Error, 'invalid operation' unless %w[comment attachment resolve].include?(key) || key.match?(/\Aresolve:[a-zA-Z0-9_-]+\z/)
    operation = bug['operations'][key]
    case command
    when 'intent'
      raise Error, 'remote changed' if bug['remote_changed']
      raise Error, 'operation already done; do not repeat' if operation && operation['status'] == 'done'
      raise Error, 'operation inflight; reconcile first' if operation && operation['status'] == 'inflight'
      raise Error, 'snapshot must be re-read before each write' unless input.fetch('snapshot') == bug['snapshot']
      fingerprint = input.fetch('payload_sha256')
      raise Error, 'payload SHA-256 required' unless fingerprint.match?(/\A[0-9a-f]{64}\z/)
      bug['operations'][key] = { 'status' => 'inflight', 'payload_sha256' => fingerprint }
    when 'receipt', 'reconcile'
      raise Error, 'no inflight operation' unless operation && operation['status'] == 'inflight'
      observed = input.fetch('observed')
      raise Error, 'invalid observed result' unless %w[present absent unknown].include?(observed)
      if observed == 'present'
        raise Error, 'receipt must confirm same payload' unless input.fetch('payload_sha256') == operation['payload_sha256']
        operation['receipt_id'] = input.fetch('receipt_id')
        operation['status'] = 'done'
      elsif observed == 'absent'
        raise Error, 'only reconciliation can permit retry' unless command == 'reconcile' && input['definitive'] == true
        operation['status'] = 'retryable'
      end
    else
      raise Error, 'unknown command'
    end
  end

  def report(state, input)
    complete = state['frozen'] && state['bugs'].all? do |bug|
      bug['status'] == 'COMMITTED' && !bug['remote_changed'] &&
        %w[comment resolve].all? { |op| bug['operations'].dig(op, 'status') == 'done' } &&
        bug['operations'].values.all? { |op| op['status'] == 'done' }
    end
    { 'batch_id' => state['batch_id'],
      'status' => complete && input['delivery_status'] == 'published' ? 'COMPLETE' : 'PARTIAL',
      'waiting_acceptance' => state['require_acceptance'] && state['bugs'].any? { |b| b['status'] == 'VALIDATED' && !b['accepted'] },
      'frozen' => state['frozen'], 'bugs' => state['bugs'], 'pushed' => false }
  end
end

if $PROGRAM_NAME == __FILE__
  options = {}
  parser = OptionParser.new do |o|
    o.banner = 'batch_state.rb COMMAND --state /outside/repo/batch.json [--input JSON_FILE|-]'
    o.on('--state PATH') { |v| options[:state] = v }
    o.on('--input PATH') { |v| options[:input] = v }
  end
  begin
    parser.parse!
    input = options[:input] ? JSON.parse(options[:input] == '-' ? $stdin.read : File.read(options[:input])) : {}
    puts JSON.pretty_generate(TapdBatchState.run(ARGV.fetch(0), options.fetch(:state), input))
  rescue TapdBatchState::Error, KeyError, ArgumentError, SystemCallError, JSON::ParserError => e
    warn "batch_state: #{e.message}"
    exit 1
  end
end
