<?php
/**
 * @brief        rigctld API
 * @date         2018-12-03
 * @author       Manawyrm
 * @copyright    MIT-licensed
 *
 */
class rigctldAPI
{
	private $host; 
	private $port;
	private $socket = false; 
	private $lastCommandFailed = false;
	private $lastRigErrorCode = 0;
	function __construct($host = "127.0.0.1", $port = 4532)
	{
		$this->host = $host; 
		$this->port = $port;

		$this->connect();
	}
	function __destruct()
	{
		if (isset($this->fp) && is_resource($this->fp))
			fclose($this->fp);
	}

	public function connect()
	{
		$this->fp = fsockopen($this->host, $this->port, $errno, $errstr, 5);
		if (!$this->fp)
		{
			$this->lastCommandFailed = true;
			$this->lastRigErrorCode = 0;
			return false; 
		}

		$this->lastCommandFailed = false;
		$this->lastRigErrorCode = 0;

		return true;
	}

	public function hasConnectionError()
	{
		return $this->lastCommandFailed;
	}

	private function invalidateConnection()
	{
		if (isset($this->fp) && is_resource($this->fp))
			fclose($this->fp);

		$this->fp = false;
		$this->lastCommandFailed = true;
	}

	private function runCommand($command, $returnSize = 1)
	{
		if ($this->fp === false)
		{
			$this->lastCommandFailed = true;
			$this->lastRigErrorCode = 0;
			return false; 
		}

		if (feof($this->fp))
		{
			$this->invalidateConnection();
			$this->lastRigErrorCode = 0;
			return false; 
		}
		
		stream_set_timeout($this->fp, 2);

		if (fwrite($this->fp, $command . "\n") === false)
		{
			$this->invalidateConnection();
			$this->lastRigErrorCode = 0;
			return false;
		}

		$result = [];
		for ($i=0; $i < $returnSize; $i++)
		{ 
			$line = fgets($this->fp);
			if ($line === false)
			{
				$meta = stream_get_meta_data($this->fp);
				if (!empty($meta['timed_out']))
				{
					$this->lastCommandFailed = false;
					$this->lastRigErrorCode = 0;
				}
				else
				{
					$this->invalidateConnection();
					$this->lastRigErrorCode = 0;
				}
				return false;
			}

			$line = trim($line);
			if (preg_match('/^RPRT (-?\d+)$/', $line, $matches) === 1)
			{
				$this->lastCommandFailed = false;
				$this->lastRigErrorCode = (int)$matches[1];
				return false;
			}

			$result[] = $line;
		}

		$this->lastCommandFailed = false;
		$this->lastRigErrorCode = 0;
		
		if ($returnSize === 1)
			return $result[0];

		return implode("\n", $result);
	}

	private function normalizeFrequency($frequency)
	{
		if (!is_numeric($frequency))
			return $frequency;

		return (string)(intdiv((int)$frequency, 10) * 10);
	}

	private function isValidFrequency($frequency)
	{
		return is_numeric($frequency) && (float)$frequency > 0;
	}

	private function isValidMode($mode)
	{
		return is_string($mode) && trim($mode) !== "";
	}

	private function hasMalformedRigResponse($frequency, $mode)
	{
		return !$this->isValidFrequency($frequency) || !$this->isValidMode($mode);
	}

	public function getFrequencyAndMode()
	{
		$frequency = $this->getFrequency();
		if ($frequency === false)
			return false; 

		$mode = $this->getMode();
		if ($mode === false)
			return false;

		if ($this->hasMalformedRigResponse($frequency, $mode['mode']))
		{
			$this->invalidateConnection();
			return false;
		}

		return [
			"frequency" => $frequency,
			"mode" => $mode['mode'],
			"passband" => $mode['passband']
		];
	}

	public function getFrequencyModeAndPower()
	{
		$data = $this->getFrequencyAndMode();
		if ($data === false)
			return false;

		$power = $this->getPowerInWatts($data['frequency'], $data['mode']);
		$data['power'] = $power === false ? '' : $power;

		return $data;
	}


	public function getFrequency()
	{
		$frequency = $this->runCommand("f");
		if ($frequency === false)
			return false;

		if (!$this->isValidFrequency($frequency))
		{
			$this->invalidateConnection();
			return false;
		}

		return $this->normalizeFrequency($frequency);
	}

	public function getMode()
	{
		$mode = $this->runCommand("m", 2); 
		if ($mode === false)
			return false; 

		$mode = explode("\n", $mode); 
		if (count($mode) < 2)
		{
			$this->invalidateConnection();
			return false;
		}

		if (!$this->isValidMode($mode[0]))
		{
			$this->invalidateConnection();
			return false;
		}

		return [
			"mode" => $mode[0],
			"passband" => $mode[1]
		];
	}

	public function getPower()
	{
		$power = $this->runCommand("l RFPOWER");
		if ($power === false || !is_numeric($power))
			return false;

		return (float)$power;
	}

	public function getPowerInWatts($frequency, $mode)
	{
		$power = $this->getPower();
		if ($power === false)
			return false;

		$milliwatts = $this->runCommand("2 " . $power . " " . $frequency . " " . $mode);
		if ($milliwatts === false || !is_numeric($milliwatts))
			return false;

		return (float)$milliwatts / 1000;
	}
}
