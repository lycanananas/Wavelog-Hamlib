#!/usr/bin/php
<?php
/**
 * @brief        Cloudlog rigctld Interface
 * @date         2018-12-02
 * @author       Manawyrm
 * @copyright    MIT-licensed
 *
 */

include("config.php");
include("rigctld.php"); 

$rigctl = new rigctldAPI($rigctl_host, $rigctl_port); 

$lastFrequency = false; 
$lastMode = false; 
$lastPower = false;
$radioDataUnavailable = false;

while (true)
{
	$data = $rigctl->getFrequencyModeAndPower();

	// check if we've gotten a proper response from rigctld
	if ($data !== false)
	{
		if ($radioDataUnavailable)
		{
			echo "Radio data available again. Resuming Cloudlog updates.\n";
			$radioDataUnavailable = false;
		}

		// only send POST to cloudlog if the settings have changed
		if ($lastFrequency != $data['frequency'] || $lastMode != $data['mode'] || $lastPower != $data['power'])
		{
			$data = [
				"radio" => $radio_name,
				"frequency" => $data['frequency'],
				"mode" => $data['mode'],
				"power" => $data['power'], // Optional field defined in watts
				"key" => $cloudlog_apikey
			];

			if (postInfoToCloudlog($cloudlog_url, $data))
			{
				$lastMode = $data['mode'];
				$lastFrequency = $data['frequency'];
				$lastPower = $data['power'];

				echo "Updated info. Frequency: " . $data['frequency'] . " - Mode: " . $data['mode'] . " - Power: " . $data['power'] . "\n";
			}
			else
			{
				echo "Failed to update info. Frequency: " . $data['frequency'] . " - Mode: " . $data['mode'] . " - Power: " . $data['power'] . "\n";
			}
		}
		
	}
	else
	{
		if (!$radioDataUnavailable)
		{
			echo "Radio data unavailable. Skipping Cloudlog update.\n";
			$radioDataUnavailable = true;
		}

		if ($rigctl->hasConnectionError())
			$rigctl->connect();
	}

	sleep($interval);
}


function postInfoToCloudlog($url, $data)
{
	$json = json_encode($data, JSON_PRETTY_PRINT);
	if ($json === false)
	{
		echo "Cloudlog POST error: JSON encode failed: " . json_last_error_msg() . "\n";
		return false;
	}

	$ch = curl_init( $url . '/api/radio' );
	if ($ch === false)
	{
		echo "Cloudlog POST error: could not initialize cURL.\n";
		return false;
	}

	curl_setopt($ch, CURLOPT_CUSTOMREQUEST, "POST"); 
	curl_setopt($ch, CURLOPT_POSTFIELDS, $json);
	curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
	curl_setopt($ch, CURLOPT_HTTPHEADER, [
		'Content-Type: application/json',
		'Content-Length: ' . strlen($json)
	]); 

	$result = curl_exec($ch);
	if ($result === false)
	{
		echo "Cloudlog POST error: cURL request failed: " . curl_error($ch) . "\n";
		curl_close($ch);
		return false;
	}

	$httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
	if ($httpCode >= 400)
	{
		echo "Cloudlog POST error: HTTP " . $httpCode . " returned by server.";
		if ($result !== '')
		{
			echo " Response: " . $result;
		}
		echo "\n";
		curl_close($ch);
		return false;
	}

	curl_close($ch);
	return true;
}
