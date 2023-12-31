# import the necessary packages

import string

#import torch
from imutils.object_detection import non_max_suppression
import numpy as np
import argparse
import time
import cv2
import keras.backend as K
from tensorflow import keras
import tensorflow as tf
#print("Cuda Availability: ", tf.test.is_built_with_cuda())
#print("GPU  Availability: ", tf.test.is_gpu_available())

#print("Num GPUs Available: ", len(tf.config.list_physical_devices('GPU')))

# construct the argument parser and parse the arguments
ap = argparse.ArgumentParser()
ap.add_argument("-i", "--image", type=str,
	help="path to input image")
ap.add_argument("-east", "--east", type=str,
	help="path to input EAST text detector")
ap.add_argument("-c", "--min-confidence", type=float, default=0.7,
	help="minimum probability required to inspect a region")
ap.add_argument("-w", "--width", type=int, default=640,
	help="nearest multiple of 32 for resized width")
ap.add_argument("-e", "--height", type=int, default=800,
	help="nearest multiple of 32 for resized height")
ap.add_argument("-p", "--padding", type=float, default=0.1,
	help="amount of padding to add to each border of ROI")
args = vars(ap.parse_args())


m3=keras.models.load_model('text_recog_model5.h5',compile=False)
net = cv2.dnn.readNet('frozen_east_text_detection.pb')


char_list = string.ascii_letters+string.digits +  string.punctuation + ' '


def pre_image(image):
    orig = image.copy()
    (origH, origW) = image.shape[:2]
    # set the new width and height and then determine the ratio in change
    # for both the width and height
    (newW, newH) = (args["width"], args["height"])
    rW = origW / float(newW)
    rH = origH / float(newH)
    # resize the image and grab the new image dimensions
    image = cv2.resize(image, (newW, newH))
    # Apply denoising (Gaussian blur)
#    image = cv2.GaussianBlur(image, (3, 3), 0)
    (H, W) = image.shape[:2]
    return rW,rH,origW,origH,W,H,image,orig

def decode_predictions(scores, geometry):
    # grab the number of rows and columns from the scores volume, then
    # initialize our set of bounding box rectangles and corresponding
    # confidence scores
    (numRows, numCols) = scores.shape[2:4]
    rects = []
    confidences = []
    # loop over the number of rows
    for y in range(0, numRows):
        # extract the scores (probabilities), followed by the
        # geometrical data used to derive potential bounding box
        # coordinates that surround text
        scoresData = scores[0, 0, y]
        xData0 = geometry[0, 0, y]
        xData1 = geometry[0, 1, y]
        xData2 = geometry[0, 2, y]
        xData3 = geometry[0, 3, y]
        anglesData = geometry[0, 4, y]
        # loop over the number of columns
        for x in range(0, numCols):
            # if our score does not have sufficient probability,
            # ignore it
            if scoresData[x] < args["min_confidence"]:
                continue
            # compute the offset factor as our resulting feature
            # maps will be 4x smaller than the input image
            (offsetX, offsetY) = (x * 4.0, y * 4.0)
            # extract the rotation angle for the prediction and
            # then compute the sin and cosine
            angle = anglesData[x]
            cos = np.cos(angle)
            sin = np.sin(angle)
            # use the geometry volume to derive the width and height
            # of the bounding box
            h = xData0[x] + xData2[x]
            w = xData1[x] + xData3[x]
            # compute both the starting and ending (x, y)-coordinates
            # for the text prediction bounding box
            endX = int(offsetX + (cos * xData1[x]) + (sin * xData2[x]))
            endY = int(offsetY - (sin * xData1[x]) + (cos * xData2[x]))
            startX = int(endX - w)
            startY = int(endY - h)
            # add the bounding box coordinates and probability score
            # to our respective lists
            rects.append((startX, startY, endX, endY))
            confidences.append(scoresData[x])
    # return a tuple of the bounding boxes and associated confidences
    return (rects, confidences)
def east(W,H,image,net):
    layerNames = [
        "feature_fusion/Conv_7/Sigmoid",
        "feature_fusion/concat_3"]
    # load the pre-trained EAST text detector
    print("[INFO] loading EAST text detector...")
    start = time.time()
    # construct a blob from the image and then perform a forward pass of
    # the model to obtain the two output layer sets
    blob = cv2.dnn.blobFromImage(image, 1.0, (W, H),
                                 (123.68, 116.78, 103.94), swapRB=True, crop=False)
    start = time.time()
    net.setInput(blob)
    (scores, geometry) = net.forward(layerNames)
    # show timing information on text prediction
    end = time.time()
    print("[INFO] text detection took {:.6f} seconds".format(end - start))
    (rects, confidences) = decode_predictions(scores, geometry)
    boxes = non_max_suppression(np.array(rects), probs=confidences)
    return boxes

def preprocess_image(img):
    input_shape = (128, 32)
    resized_frame = cv2.resize(img, input_shape)
    # Reshape the preprocessed frame to have a single channel
    preprocessed_frame = cv2.cvtColor(resized_frame, cv2.COLOR_RGB2GRAY)
    preprocessed_frame = np.expand_dims(preprocessed_frame, axis=-1)
    return preprocessed_frame

def recognize_text(img,threshold=0.8):
    # predict outputs on validation images
    prediction=m3.predict(img)
    # use CTC decoder
    out = K.get_value(K.ctc_decode(prediction, input_length=np.ones(prediction.shape[0]) * prediction.shape[1],
                                   greedy=True)[0][0])
    # Convert character index to actual characters and select the highest probability characters
    selected_chars = []
    recognized_text=''
    invalid_chars = [' ', '#', '$']  # Add the invalid characters to this list

    for i, x in enumerate(out):
        chars = ''
        for p in x:
            if int(p) not in [char_list.index(c) for c in invalid_chars]:
                chars += char_list[int(p)]
        selected_chars.append(chars)

        # Filter out low-probability characters based on the threshold
        filtered_chars = [chars for chars in selected_chars if chars and max(prediction[0, i]) >= threshold]
        # Sort the filtered characters based on their probability

        text = ' '.join(filtered_chars)
        recognized_text+=text

    return out , recognized_text

def return_results(rW,rH,origW,origH,orig,boxes):
    results = []
    for (startX, startY, endX, endY) in boxes:
        # scale the bounding box coordinates based on the respective
        # ratios
        startX = int(startX * rW)
        startY = int(startY * rH)
        endX = int(endX * rW)
        endY = int(endY * rH)
        # in order to obtain a better OCR of the text we can potentially
        # apply a bit of padding surrounding the bounding box -- here we
        # are computing the deltas in both the x and y directions
        dX = int((endX - startX) * args["padding"])
        dY = int((endY - startY) * args["padding"])
        # apply padding to each side of the bounding box, respectively
        startX = max(0, startX - dX)
        startY = max(0, startY - dY)
        endX = min(origW, endX + (dX * 2))
        endY = min(origH, endY + (dY * 2))
        # extract the actual padded ROI
        roi = orig[startY:endY, startX:endX]

#        config = ("-l eng --oem 1 --psm 7")
#        text = pytesseract.image_to_string(roi, lang='eng', config=tessdata_dir_config)

        preprocessed_frame=preprocess_image(roi)

        p,text = recognize_text(np.array([preprocessed_frame]))
        #text=easy_ocr(roi)

        # add the bounding box coordinates and OCR'd text to the list
        # of results
        results.append(((startX, startY, endX, endY), text))
    results = sorted(results, key=lambda r: r[0][1])
    return results

def display(frame):
    rW,rH,origW,origH,W,H,image,orig=pre_image(frame)
    boxes=east(W,H,image,net)
    results=return_results(rW, rH, origW, origH, orig, boxes)
    combined_text = ""
    print("OCR Text", )
    print("========")

    # display the text OCR'd by Tesseract
    for ((startX, startY, endX, endY), text) in results:
        # strip out non-ASCII text so we can draw the text on the image
        # using OpenCV, then draw the text and a bounding box surrounding
        # the text region of the input image
        text = "".join([c if ord(c) < 128 else "" for c in text]).strip()
        output = orig.copy()
        # Concatenate the recognized text from each word
        combined_text += text + " "
        combined_text=combined_text.lower()
        #cv2.putText(image, str(text), (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2, cv2.LINE_AA)
        cv2.rectangle(frame, (startX, startY), (endX, endY),
                      (0, 255,0), 2)
        cv2.putText(frame, combined_text, (startX, startY - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
        # Print the combined text
    return combined_text

# Path to input video file
input_file = "ocr4.mp4"

# Create a VideoCapture object
cap = cv2.VideoCapture(input_file)

# Get the video properties
fps = cap.get(cv2.CAP_PROP_FPS)
frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
# Define the output video writer
output_file = "output4.mp4"  # Change the file extension to .mp4
fourcc = cv2.VideoWriter_fourcc(*"mp4v")  # Use the appropriate fourcc code for MP4
out = cv2.VideoWriter(output_file, fourcc, fps, (frame_width, frame_height))



while True:
    ret, frame = cap.read()
    if not ret:
        break

    text=display(frame)
    print("Combined Text: ", text)

    cv2.imshow("Capturing for text recog", frame)
    out.write(frame)
    time.sleep(1.5)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Release the camera and close the window
cap.release()
out.release()
cv2.destroyAllWindows()


